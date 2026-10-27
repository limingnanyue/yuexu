"""长期记忆 Service：双模式召回、写入提纯、确认/否认、管理入口。

实现细节按职责拆分：
- ``memory_support``    冷热 / 相似度 / 过滤重排 / Prompt 截断 / 熔断；
- ``memory_extractor``  LLM 抽取 + 规则兜底 + 手动记忆；
- ``memory_maintenance`` 热度衰减 / 去重 / 冷清理 / 向量 GC / 重建索引。

本文件只保留业务流程编排与缓存、数据库访问协调。
"""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.cache import CacheBackend
from backend.common.constants import MemoryMode
from backend.common.exceptions import ConflictError, NotFoundError, ValidationError
from backend.common.logger import get_logger
from backend.common.utils import (
    KeywordQuery,
    clean_text,
    extract_keywords,
    extract_query_keywords,
    keyword_idf,
    truncate,
)
from backend.core.config_loader import get_config
from backend.core.runtime import get_cache
from backend.database.models import BotAccount, MemoryEntry
from backend.repositories.memory_repo import MemoryRepo
from backend.repositories.vector_store import VectorStore, create_vector_store
from backend.services.memory_admin import export_entries, memory_stats
from backend.services.memory_extractor import (
    extract_facts,
    manual_fact,
)
from backend.services.memory_maintenance import (
    decay_hot as maintenance_decay,
    dedupe as maintenance_dedupe,
    gc_vectors as maintenance_gc,
    purge_cold as maintenance_purge,
    rebuild_index as maintenance_reindex,
)
from backend.services.memory_support import (
    CONFIRM_PATTERN,
    DENY_PATTERN,
    FUZZY_FALLBACK_KEYWORDS,
    NOISE_PATTERN,
    RecallCache,
    RecallHit,
    RecallResult,
    aux_vector_filters,
    claim_inflight,
    compose_prompt,
    filter_hits,
    get_breaker,
    get_semaphore,
    identity_fact,
    is_overview_query,
    metadata_from_entry,
    release_inflight,
    similarity,
    tier_of,
    vector_filter,
    wait_inflight,
)

logger = get_logger("yuexu.service.memory")

# 指代 / 指示词：查询里有这些词时，即使超过 16 字也需要用最近上文补实体。
# ``(?<!其)他`` 排除“其他”这类非人称用法。
_PRONOUN_QUERY = re.compile(
    r"(?:它|她|(?<!其)他|这个|那个|这只|那只|这位|那位|这件|那件|"
    r"这事|那事|对方|此人|上面|前面|刚才|之前说的|刚说的)"
)

__all__ = ["MemoryService", "RecallHit", "RecallResult"]


class MemoryService:
    """长期记忆服务（读写分离、冷热分层、双模式召回）。"""

    def __init__(
        self,
        session: AsyncSession,
        vector_store: VectorStore | None = None,
        cache: CacheBackend | None = None,
    ) -> None:
        self.session = session
        self.repo = MemoryRepo(session)
        self.config = get_config()
        self.cache = cache if cache is not None else get_cache()
        self.vector = vector_store or create_vector_store(self.config, self.repo)
        self._breaker = get_breaker(
            self.vector.name,
            int(self.config.get("memory.breaker_failures", 3)),
            int(self.config.get("memory.breaker_cooldown", 60)),
        )
        self.recall_cache = RecallCache(
            self.cache,
            self.repo,
            int(self.config.get("memory.recall_cache_ttl", 600)),
        )

    async def resolve_bot_id(self, bot_id: str) -> str:
        """账号映射到独立记忆分区；只解析一次，旧库 ID 不随原账号换库漂移。"""
        library_id = await self.session.scalar(
            select(BotAccount.memory_library_id).where(BotAccount.id == bot_id)
        )
        return library_id or bot_id

    # ------------------------------------------------------------------
    # 开关 / 基础参数
    # ------------------------------------------------------------------
    def is_enabled(self, account_settings: dict | None = None, group_rule=None) -> bool:  # noqa: ANN001
        if not self.config.get("memory.enabled", True):
            return False
        if account_settings and account_settings.get("memory") is False:
            return False
        if group_rule is not None and getattr(group_rule, "enabled_memory", True) is False:
            return False
        return True

    @property
    def fuzzy_enabled(self) -> bool:
        return bool(self.config.get("memory.fuzzy_enabled", True))

    def _number(self, key: str, default: float) -> float:
        try:
            return float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def _tier_of(self, entry: MemoryEntry) -> str:
        return tier_of(
            entry,
            self._number("memory.hot_days", 7),
            self._number("memory.warm_days", 30),
        )

    def tier_of(self, entry: MemoryEntry) -> str:
        """供后台 / 测试查看记忆冷热层级。"""
        return self._tier_of(entry)

    # ------------------------------------------------------------------
    # 双检索模式
    # ------------------------------------------------------------------
    async def detect_mode(self, text: str) -> str:
        if not self.fuzzy_enabled or not text:
            return MemoryMode.PRECISE.value
        if is_overview_query(text):
            return MemoryMode.FUZZY.value
        keywords = list(self.config.get("memory.fuzzy_keywords", []) or [])
        keywords.extend(FUZZY_FALLBACK_KEYWORDS)
        if any(keyword and keyword in text for keyword in keywords):
            return MemoryMode.FUZZY.value
        if re.search(r"(记得|印象|记忆).{0,6}(吗|么|不)", text):
            return MemoryMode.FUZZY.value
        if self.config.get("memory.fuzzy_llm_confirm", False) and await self._llm_fuzzy_confirm(text):
            return MemoryMode.FUZZY.value
        return MemoryMode.PRECISE.value

    async def _llm_fuzzy_confirm(self, text: str) -> bool:
        """LLM 二次确认是否模糊回忆类查询（``memory.fuzzy_llm_confirm`` 开启时）。

        该调用位于召回主链路之前、且不受召回超时（wait_for）约束，超时
        会直接叠加到回复延迟上，因此默认上限从固定 2s 收紧为可配置的
        ``memory.fuzzy_llm_confirm_timeout_ms``（默认 800ms，与模糊召回的
        时间预算同量级）；判定失败的后果只是少一次模式修正，宁快勿准。
        """
        try:
            from backend.services.llm_service import LLMService

            llm = LLMService(self.session)
            timeout = max(
                0.3,
                self._number("memory.fuzzy_llm_confirm_timeout_ms", 800) / 1000,
            )
            reply = await asyncio.wait_for(
                llm.chat(
                    [
                        {
                            "role": "system",
                            "content": "判断用户是否在模糊回忆过去的信息。只回答：是 或 否。",
                        },
                        {"role": "user", "content": truncate(text, 200)},
                    ],
                    max_tokens=8,
                    temperature=0.0,
                ),
                timeout=timeout,
            )
            return reply.success and ("是" in reply.content[:10] or "yes" in reply.content.lower())
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _expand_query(query: str, context_texts: Sequence[str] | None) -> str:
        """指代消解：把最近上文的实体拼进检索查询，解决「它 / 这个」无词可查。

        只扩展检索用查询（缓存 key、向量/关键词检索），模式判定仍看原句。
        触发条件从「短查询」放宽到「短查询或含指代词的中等长度查询」：像
        「你还记得我之前说的那只猫叫什么名字吗」信息不足但长度超过 16 字，
        旧逻辑会直接放弃扩展。过长且没有指代词的查询仍按自含主题处理，避免
        把无关上下文塞进检索、稀释关键词。

        上下文取最近两条，并优先使用内容二字词（IDF 覆盖率口径），最多补 4
        个实体词；只增加召回依据，不改变用户原话和模型最终回复。
        """
        if not context_texts:
            return query
        stripped = (query or "").strip()
        if not stripped:
            return query
        if len(stripped) > 32:
            return query
        if len(stripped) > 16 and not _PRONOUN_QUERY.search(stripped):
            return query
        query_tokens = set(extract_query_keywords(stripped, limit=12))
        extra: list[str] = []
        for text in list(context_texts)[-2:]:
            for keyword in extract_query_keywords(text, limit=6):
                if keyword not in query_tokens and keyword not in extra:
                    extra.append(keyword)
                if len(extra) >= 4:
                    break
            if len(extra) >= 4:
                break
        if not extra:
            return query
        return f"{stripped} {' '.join(extra[:4])}"

    # ------------------------------------------------------------------
    # 召回主流程
    # ------------------------------------------------------------------
    def aux_scopes(
        self, *, bot_id: str, scope_type: str, group_id: str | None
    ) -> list[tuple[str, str, str]]:
        """召回合并的辅助分区（群共享 / 全局），按配置开关裁剪。"""
        scopes: list[tuple[str, str, str]] = []
        if scope_type == "group" and group_id and self.config.get(
            "memory.group_shared_enabled", True
        ):
            scopes.append((bot_id, "group", str(group_id)))
        if self.config.get("memory.global_enabled", True):
            scopes.append((bot_id, "global", ""))
        return scopes

    async def recall(
        self,
        *,
        bot_id: str,
        target_type: str = "user",
        target_id: str,
        user_id: str = "",
        query: str,
        group_id: str | None = None,
        scope_type: str | None = None,
        top_k: int | None = None,
        prompt_char_budget: int | None = None,
        mode: str | None = None,
        context_texts: Sequence[str] | None = None,
    ) -> RecallResult:
        started = time.perf_counter()
        scope_type = scope_type or ("group" if group_id else "private")
        mode = mode or await self.detect_mode(query)
        if not query.strip() or not self.config.get("memory.enabled", True):
            return RecallResult(mode=mode)

        top_k = int(top_k or self.config.get("memory.top_k", 5))
        budget = int(
            min(
                prompt_char_budget if prompt_char_budget is not None
                else self.config.get("memory.max_prompt_chars", 900),
                self.config.get("memory.max_prompt_chars", 900),
            )
        )
        if budget <= 0:
            return RecallResult(mode=mode)
        bot_id = await self.resolve_bot_id(bot_id)
        # 检索查询扩展（指代消解）：只影响检索与缓存 key
        search_query = self._expand_query(query, context_texts)
        filters = vector_filter(
            bot_id, target_type, target_id, user_id, scope_type, group_id
        )
        aux_scopes = self.aux_scopes(
            bot_id=bot_id, scope_type=scope_type, group_id=group_id
        )
        aux_filters = [
            item for item in aux_vector_filters(bot_id, scope_type, group_id)
            if (bot_id, item["target_type"], item["target_id"]) in set(aux_scopes)
        ]
        cache_key = await self.recall_cache.cache_key(
            bot_id, target_type, target_id, user_id, group_id, mode, search_query, budget,
            top_k=top_k, scope_type=scope_type, aux_scopes=aux_scopes,
        )

        cached = None
        try:
            cached = await self.recall_cache.read(cache_key, mode)
        except Exception:  # noqa: BLE001 - 缓存异常不影响主链路
            logger.warning("读取记忆召回缓存失败", exc_info=True)
        if cached is not None:
            cached.latency_ms = int((time.perf_counter() - started) * 1000)
            logger.debug("记忆召回缓存命中：%s", cached.summary())
            return cached

        timeout = (
            self._number("memory.fuzzy_timeout_ms", 700)
            if mode == MemoryMode.FUZZY.value
            else self._number("memory.precise_timeout_ms", 400)
        ) / 1000
        # single-flight：相同查询并发到达（弱网重发 / 同分区齐问）共享一次检索
        flight, is_owner = claim_inflight(cache_key)
        if not is_owner:
            payload = await wait_inflight(flight, timeout * 3)
            if payload is not None:
                result = await self.recall_cache.hydrate_shared(payload, mode)
                if result is not None:
                    result.latency_ms = int((time.perf_counter() - started) * 1000)
                    logger.debug("记忆召回复用并发检索结果：%s", result.summary())
                    return result
            flight = None  # 共享等待失败：回退独立检索，不接管原 future

        shared_payload: dict[str, Any] | None = None
        owner_error: BaseException | None = None
        try:
            result, reliable = await self._recall_compute(
                mode=mode,
                started=started,
                query=query,
                search_query=search_query,
                cache_key=cache_key,
                timeout=timeout,
                bot_id=bot_id,
                target_type=target_type,
                target_id=target_id,
                user_id=user_id,
                group_id=group_id,
                scope_type=scope_type,
                top_k=top_k,
                budget=budget,
                filters=filters,
                aux_filters=aux_filters,
            )
            if result.hits:
                shared_payload = self.recall_cache.payload_from(result)
            elif reliable:
                shared_payload = self.recall_cache.empty_payload(mode)
            return result
        except BaseException as exc:  # 跟随者只感知失败事实本身，不继承异常细节
            owner_error = exc
            raise
        finally:
            if is_owner and flight is not None:
                release_inflight(cache_key, flight, shared_payload, owner_error)

    async def _recall_compute(
        self,
        *,
        mode: str,
        started: float,
        query: str,
        search_query: str,
        cache_key: str,
        timeout: float,
        bot_id: str,
        target_type: str,
        target_id: str,
        user_id: str,
        group_id: str | None,
        scope_type: str,
        top_k: int,
        budget: int,
        filters: dict[str, Any],
        aux_filters: list[dict[str, Any]] | None = None,
    ) -> tuple[RecallResult, bool]:
        """缓存未命中的完整检索管线：粗召回 → 过滤重排 → 截断组装。

        返回 ``(召回结果, 检索是否可靠完成)``；可靠完成的空结果方可写入负缓存
        或共享给 single-flight 跟随者。
        """
        aux_filters = aux_filters or []
        overview = is_overview_query(query)
        vector_available = self._breaker.allow()

        coarse_limit = int(self.config.get("memory.coarse_top_k", 8))
        degraded = False
        reliable = True
        raw_hits: list[RecallHit] = []

        try:
            if not vector_available:
                raw_hits = await self._safe_keyword_hits(
                    search_query, filters, coarse_limit, scope_type,
                    overview=overview, timeout=0.25,
                )
                degraded = True
            else:
                async with get_semaphore(int(self.config.get("memory.max_concurrency", 2))):
                    raw_hits, degraded = await asyncio.wait_for(
                        self._coarse_recall(
                            search_query, filters, coarse_limit, scope_type,
                            overview=overview,
                        ),
                        timeout=timeout,
                    )
            if not degraded:
                self._breaker.success()
        except asyncio.TimeoutError:
            self._breaker.failure()
            degraded = True
            reliable = False
            logger.warning("记忆检索超时，降级关键词召回")
            raw_hits = await self._safe_keyword_hits(
                search_query, filters, coarse_limit, scope_type,
                overview=overview, timeout=0.25,
            )
        except Exception:  # noqa: BLE001 - 向量异常不阻断对话
            self._breaker.failure()
            degraded = True
            reliable = False
            logger.exception("记忆检索异常，降级关键词召回")
            raw_hits = await self._safe_keyword_hits(
                search_query, filters, coarse_limit, scope_type,
                overview=overview, timeout=0.25,
            )

        # 辅助分区（群共享 / 全局）合并检索：best-effort，失败只少记不报错；
        # 熔断打开时不触碰向量库，整体限制在剩余预算内，不拖慢主链路。
        # 多个辅助分区并行检索（各自带独立超时），总耗时从分区数累加
        # 压到最慢一个分区，群聊 + 全局双分区时延迟近似减半。
        if aux_filters:
            async def _aux_one(aux_filter: dict[str, Any]) -> list[RecallHit]:
                if vector_available:
                    return await self._aux_hits(
                        search_query, aux_filter, coarse_limit, overview=overview,
                    )
                return await self._safe_keyword_hits(
                    search_query, aux_filter, coarse_limit, "",
                    overview=overview, timeout=0.1,
                )

            try:
                aux_merged: list[RecallHit] = []
                for hits in await asyncio.wait_for(
                    asyncio.gather(*(_aux_one(item) for item in aux_filters)),
                    timeout=0.3,
                ):
                    aux_merged = self._merge_hits(aux_merged, hits)
                raw_hits = self._merge_hits(raw_hits, aux_merged)
            except asyncio.TimeoutError:
                logger.debug("辅助分区检索超时，跳过群共享 / 全局记忆")

        # 模糊模式双路召回：向量 + 关键词。主分区与辅助分区的关键词路
        # 并行执行（各自带独立超时），模糊模式整体仍受 recall 超时约束。
        if mode == MemoryMode.FUZZY.value and self.vector.name != "keyword" and not overview:
            keyword_tasks = [
                self._safe_keyword_hits(
                    search_query, filters, coarse_limit, scope_type,
                    overview=overview, timeout=0.25,
                )
            ]
            keyword_tasks.extend(
                self._safe_keyword_hits(
                    search_query, aux_filter, coarse_limit, "", timeout=0.25,
                )
                for aux_filter in aux_filters
            )
            for hits in await asyncio.gather(*keyword_tasks):
                raw_hits = self._merge_hits(raw_hits, hits)

        threshold = self._number(
            "memory.fuzzy_threshold"
            if mode == MemoryMode.FUZZY.value
            else "memory.precise_threshold",
            0.5 if mode == MemoryMode.FUZZY.value else 0.7,
        )
        weights = (
            self.config.section("memory.rerank_weights")
            if self.config.get("memory.rerank_enabled", True)
            else None
        )
        # 过滤 / MMR 重排含 O(n²) 字符相似度计算，放入工作线程避免阻塞事件循环
        ranked = (await asyncio.to_thread(
            filter_hits,
            raw_hits,
            mode=mode,
            bot_id=bot_id,
            target_type=target_type,
            target_id=target_id,
            user_id=user_id,
            group_id=group_id,
            scope_type=scope_type,
            aux_partitions=[
                (str(item["target_type"]), str(item["target_id"])) for item in aux_filters
            ],
            threshold=threshold,
            max_fuzzy_weight=self._number("memory.precise_max_fuzzy_weight", 0.5),
            degraded=degraded,
            # 查询关键词使用内容二字词优先的集合：长问句尾部的实体也能进入
            # 重排，而不是被句首的“你还记得 / 我之前”占满 8 个名额。
            query_keywords=extract_query_keywords(search_query, limit=12),
            rerank_weights=weights,
            query=search_query,
            hot_days=self._number("memory.hot_days", 7),
            warm_days=self._number("memory.warm_days", 30),
            mmr_lambda=self._number("memory.mmr_lambda", 0.7),
        ))[:top_k]
        prompt, included = compose_prompt(ranked, mode, budget, query=search_query)
        result = RecallResult(
            mode=mode,
            hits=included,
            prompt=prompt,
            degraded=degraded,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        if included:
            try:
                await self.recall_cache.write(cache_key, result)
            except Exception:  # noqa: BLE001
                logger.warning("写入记忆召回缓存失败", exc_info=True)
        elif reliable:
            # 负缓存：检索可靠完成且无命中，短 TTL 避免同类查询反复全链路检索
            try:
                await self.recall_cache.write_empty(cache_key, mode)
            except Exception:  # noqa: BLE001
                logger.debug("写入负缓存失败", exc_info=True)
        logger.debug(
            "记忆召回完成：mode=%s hits=%s degraded=%s latency=%sms",
            mode, len(included), degraded, result.latency_ms,
        )
        return result, reliable

    async def retrieve(
        self,
        *,
        bot_id: str,
        scope_type: str = "private",
        user_id: str,
        query: str,
        group_id: str | None = None,
        top_k: int | None = None,
    ) -> list[MemoryEntry]:
        """兼容旧调用：只返回命中的记忆实体。"""
        result = await self.recall(
            bot_id=bot_id,
            target_type="user",
            target_id=user_id,
            user_id=user_id,
            query=query,
            group_id=group_id,
            scope_type=scope_type,
            top_k=top_k,
        )
        return result.entries

    async def _coarse_recall(
        self,
        query: str,
        filters: dict[str, Any],
        limit: int,
        scope_type: str,
        *,
        overview: bool = False,
    ) -> tuple[list[RecallHit], bool]:
        if overview:
            return await self._keyword_hits(query, filters, limit, scope_type, overview=True), True
        keyword_backend = self.vector.name == "keyword"
        try:
            pairs = await self.vector.search(query, limit=limit, where=filters)
        except Exception as exc:  # noqa: BLE001
            logger.warning("向量检索失败，降级关键词：%s", exc)
            return await self._keyword_hits(query, filters, limit, scope_type), True
        if not pairs:
            return await self._keyword_hits(query, filters, limit, scope_type), True

        entries = await self.repo.get_many([item_id for item_id, _score in pairs])
        by_id = {entry.id: entry for entry in entries}
        hits: list[RecallHit] = []
        for item_id, item_similarity in pairs:
            entry = by_id.get(item_id)
            if entry is None:
                continue
            hits.append(
                RecallHit(
                    entry=entry,
                    similarity=float(item_similarity),
                    source="keyword" if keyword_backend else "vector",
                )
            )
        return hits, keyword_backend

    async def _keyword_hits(
        self,
        query: str,
        filters: dict[str, Any],
        limit: int,
        scope_type: str,
        *,
        overview: bool | None = None,
    ) -> list[RecallHit]:
        # overview 由调用方按原始查询预判定（扩展后的查询会破坏整句匹配）
        if overview is None:
            overview = is_overview_query(query)
        # 内容二字词优先 + 长短语补充：长问句句尾的专名也能进入 SQL LIKE
        # 候选圈选，避免旧实现只取句首 8 个 n-gram 导致“后面问的查不到”。
        keywords = [] if overview else extract_query_keywords(query, limit=12)
        if not keywords and not overview:
            return []
        rows = await self.repo.search_candidates(
            str(filters["bot_id"]),
            keywords,
            target_type=str(filters.get("target_type") or "user"),
            target_id=str(filters.get("target_id") or ""),
            user_id=str(filters.get("user_id")) if filters.get("user_id") else None,
            group_id=str(filters.get("group_id")) if filters.get("group_id") else None,
            scope_type=scope_type,
            limit=max(limit * 3, 12),
        )
        if not rows:
            return []
        if overview:
            # 整体回顾（「你还记得我吗」）：分区内近期记忆都算相关线索，
            # 由统一重排按热度 / 置信度决定最终注入顺序。
            return [RecallHit(entry=row, similarity=1.0, source="keyword") for row in rows]
        # 关键词打分：IDF 加权覆盖率（稀有词命中权重更高，避免 2 字泛词刷分）。
        # IDF 在本次候选集上统计——候选由 SQL LIKE 圈出，已能代表本分区的词分布。
        # 查询剖析在这里构造一次，循环内只做「关键词是否出现」的判定。
        idf = self._keyword_idf(rows, keywords)
        profile = KeywordQuery(query, keywords, idf=idf)
        hits: list[RecallHit] = []
        for row in rows:
            score = profile.score(row.content or "")
            if score > 0:
                hits.append(RecallHit(entry=row, similarity=score, source="keyword"))
        # 按词法强度排序：合并进固定长度候选列表时优先保留强匹配
        hits.sort(key=lambda item: item.similarity, reverse=True)
        return hits

    @staticmethod
    def _keyword_idf(
        rows: Sequence[MemoryEntry], keywords: Sequence[str]
    ) -> dict[str, float]:
        """候选集上的平滑 IDF：``log((N+1)/(df+1)) + 1``，稀有词权重更高。"""
        return keyword_idf((row.content or "" for row in rows), keywords)

    async def _safe_keyword_hits(
        self,
        query: str,
        filters: dict[str, Any],
        limit: int,
        scope_type: str,
        *,
        overview: bool | None = None,
        timeout: float,
    ) -> list[RecallHit]:
        try:
            return await asyncio.wait_for(
                self._keyword_hits(
                    query, filters, limit, scope_type, overview=overview
                ),
                timeout=timeout,
            )
        except Exception:  # noqa: BLE001
            return []

    async def _aux_hits(
        self,
        query: str,
        aux_filter: dict[str, Any],
        limit: int,
        *,
        overview: bool = False,
    ) -> list[RecallHit]:
        """辅助分区（群共享 / 全局）检索：向量优先，失败回退关键词，均为 best-effort。"""
        try:
            pairs = await asyncio.wait_for(
                self.vector.search(query, limit=limit, where=aux_filter), timeout=0.25,
            )
        except Exception:  # noqa: BLE001 - 辅助分区失败不影响主链路
            return await self._safe_keyword_hits(
                query, aux_filter, limit, "", overview=overview, timeout=0.25,
            )
        if not pairs:
            return await self._safe_keyword_hits(
                query, aux_filter, limit, "", overview=overview, timeout=0.25,
            )
        entries = await self.repo.get_many([item_id for item_id, _score in pairs])
        by_id = {entry.id: entry for entry in entries}
        hits: list[RecallHit] = []
        for item_id, item_similarity in pairs:
            entry = by_id.get(item_id)
            if entry is not None:
                hits.append(
                    RecallHit(entry=entry, similarity=float(item_similarity), source="vector")
                )
        return hits

    @staticmethod
    def _merge_hits(primary: list[RecallHit], extra: list[RecallHit]) -> list[RecallHit]:
        merged: dict[str, RecallHit] = {hit.entry.id: hit for hit in primary}
        for hit in extra:
            existing = merged.get(hit.entry.id)
            if existing is None or hit.similarity > existing.similarity:
                merged[hit.entry.id] = hit
        return list(merged.values())

    # ------------------------------------------------------------------
    # 召回缓存失效（版本号精准失效：分区写入只失效对应分区，全局操作递增代际）
    # ------------------------------------------------------------------
    async def _bump_recall_cache(
        self, bot_id: str, target_type: str, target_id: str
    ) -> None:
        try:
            await self.recall_cache.bump(bot_id, target_type, target_id)
        except Exception:  # noqa: BLE001
            logger.debug("递增记忆召回缓存版本失败", exc_info=True)

    async def _invalidate_recall_cache(self) -> None:
        try:
            await self.recall_cache.bump_all()
        except Exception:  # noqa: BLE001
            logger.debug("递增记忆召回缓存代际失败", exc_info=True)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    async def add_memory(
        self,
        *,
        bot_id: str,
        scope_type: str,
        user_id: str,
        content: str,
        target_type: str = "user",
        target_id: str | None = None,
        group_id: str | None = None,
        category: str = "fact",
        memory_type: str = "fact",
        importance: float = 0.5,
        confidence: float = 0.7,
        fuzzy_weight: float = 0.0,
        keywords: Sequence[str] | None = None,
        hot_score: float | None = None,
        rejected: bool = False,
        source_message_id: str | None = None,
        check_duplicate: bool = True,
        library_id: str | None = None,
        index_vector: bool = True,
        duplicate_pool: list[MemoryEntry] | None = None,
    ) -> MemoryEntry | None:
        """写入一条记忆；重复 / 无效内容返回 None。

        ``index_vector=False`` 由批量写入方（``extract_and_store``）使用：一次
        抽取往往产生多条事实，逐条写向量意味着逐条做一次嵌入（onnx / api
        provider 每条都是一次模型请求），批量方会在最后统一 ``index_entries``。
        ``duplicate_pool`` 同样是批量方传入的近邻查重快照，省掉每条事实一次
        「最近 40 条」查询；单条写入不传任何参数时行为与旧实现完全一致。
        """
        generated_summary = category == "conversation_summary" and str(source_message_id or "").startswith("ctxsum_")
        limit = 1200 if generated_summary else int(self.config.get("memory.max_entry_chars", 500))
        text = clean_text(content, limit)
        if not text or (NOISE_PATTERN.search(text) and not generated_summary):
            return None
        if memory_type not in {"fact", "preference", "plan"}:
            memory_type = "fact"
        if target_type == "global":
            # 全局分区：机器人对全部会话可见，无独立目标
            target_id = ""
        else:
            target_id = target_id or (group_id if target_type == "group" else user_id) or ""
            if not target_id:
                return None

        bot_id = library_id or await self.resolve_bot_id(bot_id)
        if generated_summary:
            existing = await self.session.scalar(select(MemoryEntry.id).where(
                MemoryEntry.bot_id == bot_id, MemoryEntry.source_message_id == source_message_id,
            ).limit(1))
            if existing is not None:
                return None
        if check_duplicate and not generated_summary:
            duplicate = await self._find_duplicate(
                bot_id=bot_id,
                target_type=target_type,
                target_id=target_id,
                user_id=user_id,
                group_id=group_id,
                content=text,
                category=category,
                recent_pool=duplicate_pool,
            )
            if duplicate is not None:
                # 重复出现本身是“这条事实仍然有效”的证据：不新增行，但小幅
                # 提升原记忆的置信度 / 热度，让反复提到的偏好与身份事实在
                # 后续召回中更靠前。写操作按条目限频，避免刷屏式写放大。
                await self._touch_duplicate(duplicate)
                logger.debug("记忆重复，已回馈原条目：%s", truncate(text, 30))
                return None

        entry = await self.repo.create(
            bot_id=bot_id,
            target_type=target_type,
            target_id=target_id,
            scope_type=scope_type,
            group_id=group_id,
            user_id=user_id,
            content=text,
            category=category,
            memory_type=memory_type,
            importance=importance,
            confidence=min(1.0, max(0.0, confidence)),
            fuzzy_weight=min(1.0, max(0.0, fuzzy_weight)),
            hot_score=(
                self._number("memory.hot_score_init", 5.0)
                if hot_score is None
                else hot_score
            ),
            tag_keywords=list(keywords or extract_keywords(text, limit=6)),
            rejected=rejected,
            source_message_id=source_message_id,
        )
        if index_vector:
            await self.index_entries([entry])
        # 身份事实自动更正：新值落库成功后再作废同属性的旧值，避免创建失败时
        # 旧记忆已经被清掉（先写后删，任何一步失败都还有一份可用记忆）。
        if not generated_summary and self.config.get("memory.supersede_enabled", True):
            await self._supersede_identity_facts(entry)
        await self._bump_recall_cache(entry.bot_id, entry.target_type, entry.target_id)
        return entry

    async def index_entries(self, entries: Sequence[MemoryEntry]) -> int:
        """批量写向量索引：一次嵌入调用代替「每条记忆一次调用」。

        长消息一次可抽取 8 条事实，群聊还会同步写入群共享分区；旧实现每条
        事实各调一次 ``vector.add``（内置稀疏嵌入是纯 CPU，onnx / api 嵌入
        则每条都是一次模型请求，8 条事实因此多等 8 次往返、也更容易撞上
        服务商限流）。这里合并为一次批量写入，返回成功写入的条数。
        向量失败仍然只记日志——数据库记忆才是事实来源。
        """
        items = [entry for entry in entries if entry is not None]
        if not items:
            return 0
        try:
            await self.vector.add(
                [entry.id for entry in items],
                [entry.content or "" for entry in items],
                [metadata_from_entry(entry) for entry in items],
            )
            return len(items)
        except Exception as exc:  # noqa: BLE001 - 向量失败不影响数据库记忆
            logger.warning("向量索引批量写入失败（已保留数据库记忆）：%s", exc)
            return 0

    async def _supersede_identity_facts(self, entry: MemoryEntry) -> list[MemoryEntry]:
        """身份事实自动更正：同属性只保留最新值（搬家 / 改名 / 年龄变化）。

        只处理姓名、居住地、年龄、生日四类确定性属性，且要求新旧值不同；
        偏好、经历、计划等可以并存的记忆不受影响，避免误删。
        旧记忆标记 ``rejected``（不再参与召回，后台仍可查看），并同步向量元数据。
        """
        if entry.category in {"conversation_summary", "emotion", "experience"}:
            return []
        fact = identity_fact(entry.content)
        if fact is None:
            return []
        key, value = fact
        # 用属性模式圈选全部历史身份候选，而不是只看最近 60 条：用户聊了
        # 几十轮日常后再搬家，旧住址仍应被新值作废。
        candidates = await self.repo.identity_candidates(
            entry.bot_id,
            target_type=entry.target_type,
            target_id=entry.target_id,
            user_id=entry.user_id,
            group_id=entry.group_id,
        )
        stale: list[MemoryEntry] = []
        for other in candidates:
            if other.id == entry.id or other.rejected:
                continue
            other_fact = identity_fact(other.content)
            if other_fact is None or other_fact[0] != key or other_fact[1] == value:
                continue
            stale.append(other)
        if not stale:
            return []
        for other in stale:
            other.rejected = True
            other.confidence = max(0.0, float(other.confidence or 0) - 0.2)
            other.hot_score = 0.0
        # 旧值作废后立即刷写，保证下一次召回（可能来自并发会话）看到的是新状态
        await self.session.flush()
        try:
            await self.vector.update_metadata(
                [other.id for other in stale], {"rejected": True}
            )
        except Exception:  # noqa: BLE001 - 向量元数据失败可由重建索引修复
            logger.debug("同步身份旧记忆向量元数据失败", exc_info=True)
        await self._bump_entries_scope(stale)
        logger.info(
            "身份事实更正（%s）：作废旧记忆 %s 条，新值=%s",
            key, len(stale), truncate(value, 20),
        )
        return stale

    async def _find_duplicate(
        self,
        *,
        bot_id: str,
        target_type: str,
        target_id: str,
        user_id: str,
        group_id: str | None,
        content: str,
        category: str = "fact",
        recent_pool: list[MemoryEntry] | None = None,
    ) -> MemoryEntry | None:
        """查找已有重复记忆，返回原条目而不是布尔值（用于重复证据回馈）。

        顺序：精确文本 → 向量相似度 → 最近 40 条字符相似度。任一步命中即
        返回；被用户否认（rejected）的旧条目不算重复，允许用户重新建立记忆。

        ``recent_pool`` 由批量写入方复用：一次抽取的多条事实属于同一个分区，
        近邻快照只需取一次（旧实现每条事实都查一次「最近 40 条」）。批量方
        会把本批新增的条目追加进快照，因此同批事实之间仍然互相查重。
        """
        exact = await self.repo.find_exact(
            bot_id,
            target_type=target_type,
            target_id=target_id,
            user_id=user_id,
            group_id=group_id,
            content=content,
        )
        if exact is not None and not exact.rejected:
            return exact
        dated = re.match(r"^记录日期 (\d{4}-\d{2}-\d{2})[：:]", content)
        record_date = dated.group(1) if dated and category in {"emotion", "experience"} else None
        threshold = self._number("memory.dedupe_threshold", 0.9)
        filters = vector_filter(
            bot_id, target_type, target_id, user_id,
            "group" if group_id else "private", group_id,
        )
        try:
            pairs = await asyncio.wait_for(
                self.vector.search(content, limit=3, where=filters), timeout=1.5
            )
            if pairs and pairs[0][1] >= threshold:
                if record_date is None:
                    candidate = await self.repo.get(pairs[0][0])
                    # 向量分数经 ×7 校准后接近饱和（弱重叠也能到 1.0），必须再用
                    # 原文相似度确认；否则「相关但不同」的新事实会被当成重复丢掉。
                    if (
                        candidate is not None
                        and not candidate.rejected
                        and similarity(content, candidate.content or "", threshold=threshold) >= threshold
                    ):
                        return candidate
                else:
                    for entry_id, score in pairs:
                        if score < threshold:
                            continue
                        entry = await self.repo.get(entry_id)
                        if (
                            entry
                            and not entry.rejected
                            and entry.category in {"emotion", "experience"}
                            and re.match(rf"^记录日期 {record_date}[：:]", entry.content)
                            and similarity(content, entry.content or "", threshold=threshold) >= threshold
                        ):
                            return entry
        except Exception:  # noqa: BLE001 - 向量检索失败时仍走近邻字符查重
            logger.debug("向量查重失败，回退近邻字符相似度", exc_info=True)
        if recent_pool is None:
            recent: Sequence[MemoryEntry] = await self.repo.recent_for_target(
                bot_id,
                target_type=target_type,
                target_id=target_id,
                user_id=user_id,
                group_id=group_id,
                limit=40,
            )
        else:
            recent = recent_pool
        if not recent:
            return None
        # 40 条近邻的 O(n) 字符相似度扫描（SequenceMatcher）放入工作线程，
        # 写入路径不阻塞事件循环
        return await asyncio.to_thread(
            self._scan_recent_duplicates, content, record_date, recent, threshold
        )

    async def _is_duplicate(self, **kwargs: Any) -> bool:
        """兼容旧内部调用：只关心是否存在重复。"""
        return await self._find_duplicate(**kwargs) is not None

    @staticmethod
    def _scan_recent_duplicates(
        content: str,
        record_date: str | None,
        recent: Sequence[MemoryEntry],
        threshold: float,
    ) -> MemoryEntry | None:
        date_prefix = (
            re.compile(rf"^记录日期 {record_date}[：:]") if record_date else None
        )
        for entry in recent:
            if date_prefix is not None and not (
                entry.category in {"emotion", "experience"}
                and date_prefix.match(entry.content or "")
            ):
                continue
            if similarity(content, entry.content or "", threshold=threshold) >= threshold:
                return entry
        return None

    async def _touch_duplicate(self, entry: MemoryEntry) -> bool:
        """重复提及回馈：原条目小幅升置信 / 升热，按条目限频写库。

        与 ``reinforce``（召回成功后的热度回馈）区分：这里代表“用户又说了一遍
        同一事实”，不增加 hit_count，也不改变模糊权重。默认 24 小时最多一次，
        既保留重复证据，又避免每轮闲聊都写数据库。
        """
        if entry.rejected or not self.config.get("memory.duplicate_reinforce", True):
            return False
        interval = int(self._number("memory.duplicate_reinforce_interval", 86400))
        marker = f"memdup:{entry.id}"
        if interval > 0:
            try:
                if await self.cache.get(marker):
                    return False
            except Exception:  # noqa: BLE001 - 缓存故障不阻断写入
                logger.debug("读取重复记忆回馈标记失败", exc_info=True)
        confidence_boost = max(0.0, self._number("memory.duplicate_confidence_boost", 0.03))
        hot_boost = max(0.0, self._number("memory.duplicate_hot_boost", 0.1))
        old_confidence = float(entry.confidence or 0)
        old_hot = float(entry.hot_score or 0)
        entry.confidence = min(1.0, old_confidence + confidence_boost)
        entry.hot_score = min(10.0, old_hot + hot_boost)
        if entry.confidence == old_confidence and entry.hot_score == old_hot:
            return False
        await self.session.flush()
        if interval > 0:
            try:
                await self.cache.set(marker, "1", ttl=interval)
            except Exception:  # noqa: BLE001
                logger.debug("写入重复记忆回馈标记失败", exc_info=True)
        # 置信度 / 热度参与重排，必须让本分区召回缓存失效。
        await self._bump_entries_scope([entry])
        logger.debug(
            "重复记忆回馈：%s（confidence %.2f→%.2f, hot %.2f→%.2f）",
            entry.id, old_confidence, entry.confidence, old_hot, entry.hot_score,
        )
        return True

    async def extract_and_store(
        self,
        event,  # noqa: ANN001 - BotEvent（避免服务层循环依赖）
        user_text: str,
        assistant_text: str = "",
        *,
        manual: bool = False,
        record_date: str | None = None,
        skip_interval: bool = False,
        strict_extraction: bool = False,
    ) -> list[MemoryEntry]:
        """从用户发言中抽取长期事实并入库（异步后台调用）。"""
        if not user_text:
            return []
        if not manual and not skip_interval and not await self._extraction_due(event):
            return []
        facts = (
            [manual_fact(user_text)]
            if manual
            else await extract_facts(
                self.session,
                user_text,
                bot_id=event.bot_id,
                group_id=event.group_id,
                llm_enabled=bool(self.config.get("memory.llm_extract", True)),
                timeout=self._number("memory.extract_timeout", 8),
                record_date=record_date,
                strict_extraction=strict_extraction,
                # 长消息多段并发抽取；默认 2 路，避免把服务商限流打满。
                llm_concurrency=int(self.config.get("memory.extract_concurrency", 2)),
            )
        )
        stored: list[MemoryEntry] = []
        group_shared = (
            event.is_group
            and bool(event.group_id)
            and bool(self.config.get("memory.group_shared_extract", True))
        )
        # 一次抽取会产出多条事实（群聊还会同步写入群共享分区）。旧实现每条
        # 事实都要：查一次向量嵌入 + 查一次「最近 40 条」做字符查重，8 条事实
        # 就是 8 次嵌入调用（onnx / api provider 每次都是一次模型请求）与 8 次
        # 查询。这里按分区各取一次近邻快照复用，并把向量索引推迟到循环结束后
        # 一次性批量写入；本批新增的条目会追加进快照，同批事实之间仍然互相
        # 查重（语义与逐条查询一致）。
        pools: dict[tuple[str, str, str | None], list[MemoryEntry]] = {}
        bot_id = await self.resolve_bot_id(event.bot_id)

        async def pool_for(
            target_type: str, target_id: str, group_id: str | None
        ) -> list[MemoryEntry]:
            key = (target_type, target_id, group_id)
            pool = pools.get(key)
            if pool is None:
                pool = list(await self.repo.recent_for_target(
                    bot_id,
                    target_type=target_type,
                    target_id=target_id,
                    user_id=event.user_id,
                    group_id=group_id,
                    limit=40,
                ))
                pools[key] = pool
            return pool

        def remember(pool: list[MemoryEntry], entry: MemoryEntry) -> None:
            """把本批新条目并入快照，并保持快照规模与「最近 40 条」一致。"""
            pool.append(entry)
            if len(pool) > 40:
                del pool[: len(pool) - 40]

        for fact in facts:
            user_pool = await pool_for("user", str(event.user_id), event.group_id)
            entry = await self.add_memory(
                bot_id=event.bot_id,
                target_type="user",
                target_id=event.user_id,
                scope_type=event.scene.value,
                group_id=event.group_id,
                user_id=event.user_id,
                content=str(fact.get("content") or ""),
                category=str(fact.get("category") or "fact"),
                memory_type=str(fact.get("memory_type") or "fact"),
                importance=float(fact.get("confidence") or 0.7),
                confidence=float(fact.get("confidence") or 0.7),
                fuzzy_weight=float(fact.get("fuzzy_weight") or 0.1),
                keywords=fact.get("keywords") or None,
                source_message_id=event.message_id,
                index_vector=False,
                duplicate_pool=user_pool,
            )
            if entry is not None:
                stored.append(entry)
                remember(user_pool, entry)
            # 群聊事实同步写入群共享分区：群内所有成员的对话都可召回
            if group_shared:
                shared_pool = await pool_for("group", str(event.group_id), str(event.group_id))
                shared = await self.add_memory(
                    bot_id=event.bot_id,
                    target_type="group",
                    target_id=str(event.group_id),
                    scope_type="group",
                    group_id=str(event.group_id),
                    user_id=event.user_id,
                    content=str(fact.get("content") or ""),
                    category=str(fact.get("category") or "fact"),
                    memory_type=str(fact.get("memory_type") or "fact"),
                    importance=float(fact.get("confidence") or 0.7),
                    confidence=float(fact.get("confidence") or 0.7),
                    fuzzy_weight=float(fact.get("fuzzy_weight") or 0.1),
                    keywords=fact.get("keywords") or None,
                    source_message_id=event.message_id,
                    index_vector=False,
                    duplicate_pool=shared_pool,
                )
                if shared is not None:
                    stored.append(shared)
                    remember(shared_pool, shared)
        if stored:
            # 批量写索引：一次嵌入调用覆盖本轮全部新记忆，失败不影响数据库记忆
            await self.index_entries(stored)
            logger.info("写入长期记忆 %s 条：%s", len(stored), event.user_id)
        return stored

    async def _extraction_due(self, event) -> bool:  # noqa: ANN001
        """memory.extract_interval 节流：距上次抽取不足间隔则跳过本轮。"""
        interval = int(self.config.get("memory.extract_interval", 0) or 0)
        if interval <= 0:
            return True
        marker = f"memextract:{event.session_key()}"
        try:
            last = await self.cache.get(marker)
            if last:
                if time.time() - float(last) < interval:
                    return False
            await self.cache.set(marker, str(time.time()), ttl=interval * 2)
        except Exception:  # noqa: BLE001 - 节流失败不阻断抽取
            logger.debug("记忆抽取节流检查失败", exc_info=True)
        return True

    async def remember_manual(self, event, content: str) -> MemoryEntry | None:  # noqa: ANN001
        fact = manual_fact(content)
        if not fact["content"]:
            return None
        return await self.add_memory(
            bot_id=event.bot_id,
            target_type="user",
            target_id=event.user_id,
            scope_type=event.scene.value,
            group_id=event.group_id,
            user_id=event.user_id,
            content=fact["content"],
            category=fact["category"],
            memory_type=fact["memory_type"],
            importance=1.0,
            confidence=1.0,
            fuzzy_weight=0.0,
            keywords=fact.get("keywords"),
            source_message_id=event.message_id,
        )

    async def forget(self, event, keyword: str) -> int:  # noqa: ANN001
        keyword = clean_text(keyword, 40).strip()
        if not keyword:
            return 0
        keywords = extract_keywords(keyword, limit=6) or [keyword]
        rows = await self.repo.search_candidates(
            await self.resolve_bot_id(event.bot_id),
            keywords,
            target_type="user",
            target_id=event.user_id,
            user_id=event.user_id,
            group_id=event.group_id,
            scope_type=event.scene.value,
            limit=100,
        )
        # 原文不含该关键字时不能退回“整批否认”：LIKE 兜底会把任何二字词命中的
        # 记忆都圈进来，一次 /forget 就会误伤几十条无关记忆。
        matched = [row for row in rows if keyword in (row.content or "")]
        if not matched:
            return 0
        return await self.reject([row.id for row in matched])

    # ------------------------------------------------------------------
    # 用户确认 / 否认
    # ------------------------------------------------------------------
    async def confirm(self, entry_ids: Sequence[str], *, bot_id: str | None = None) -> int:
        entries = await self.repo.get_many(list(entry_ids))
        if bot_id is not None:
            library_id = await self.resolve_bot_id(bot_id)
            entries = [entry for entry in entries if entry.bot_id == library_id]
        if not entries:
            return 0
        boost = self._number("memory.hot_hit_boost", 1.0)
        for entry in entries:
            entry.hot_score = min(10.0, float(entry.hot_score or 0) + boost)
            entry.confidence = min(1.0, float(entry.confidence or 0.7) + 0.1)
            entry.fuzzy_weight = max(0.0, float(entry.fuzzy_weight or 0) - 0.15)
            entry.rejected = False
            entry.hit_count = int(entry.hit_count or 0) + 1
            entry.last_hit_at = datetime.now()
        await self.session.flush()
        try:
            await self.vector.update_metadata([entry.id for entry in entries], {"rejected": False})
        except Exception:  # noqa: BLE001
            logger.debug("同步向量元数据失败（确认）", exc_info=True)
        await self._bump_entries_scope(entries)
        return len(entries)

    async def reject(self, entry_ids: Sequence[str], *, bot_id: str | None = None) -> int:
        entries = await self.repo.get_many(list(entry_ids))
        if bot_id is not None:
            library_id = await self.resolve_bot_id(bot_id)
            entries = [entry for entry in entries if entry.bot_id == library_id]
        if not entries:
            return 0
        penalty = self._number("memory.denied_penalty", 1.5)
        for entry in entries:
            entry.hot_score = max(0.0, float(entry.hot_score or 0) - penalty)
            entry.confidence = max(0.0, float(entry.confidence or 0.7) - 0.2)
            entry.rejected = True
            entry.hit_count = int(entry.hit_count or 0) + 1
            entry.last_hit_at = datetime.now()
        await self.session.flush()
        try:
            await self.vector.update_metadata([entry.id for entry in entries], {"rejected": True})
        except Exception:  # noqa: BLE001
            logger.debug("同步向量元数据失败（否认）", exc_info=True)
        await self._bump_entries_scope(entries)
        return len(entries)

    async def _bump_entries_scope(self, entries: Sequence[MemoryEntry]) -> None:
        """只失效受影响记忆分区（bot + target）的召回缓存。"""
        scopes: set[tuple[str, str, str]] = {
            (entry.bot_id, entry.target_type, entry.target_id) for entry in entries
        }
        for bot_id, target_type, target_id in scopes:
            await self._bump_recall_cache(bot_id, target_type, target_id)

    async def reinforce(
        self,
        entry_ids: Sequence[str],
        *,
        bot_id: str | None = None,
        boost: float | None = None,
        min_interval: float | None = None,
    ) -> int:
        """召回命中回馈：热度 / 命中次数 / 最近命中时间。

        与用户主动「确认」不同，这里只做很小的热度增量（默认 +0.2）并按条目
        限频（默认 6 小时一次）：反复被想起的记忆自然升为热记忆、排序更靠前，
        同时避免每轮对话都写库造成写放大。调用方应在回复发送后异步执行，
        不占用用户等待链路。
        """
        ids = [item for item in dict.fromkeys(entry_ids) if item]
        if not ids:
            return 0
        entries = await self.repo.get_many(ids)
        if bot_id is not None:
            library_id = await self.resolve_bot_id(bot_id)
            entries = [entry for entry in entries if entry.bot_id == library_id]
        boost = (
            self._number("memory.recall_reinforce_boost", 0.2)
            if boost is None else float(boost)
        )
        interval = (
            self._number("memory.recall_reinforce_interval", 21600)
            if min_interval is None else float(min_interval)
        )
        now = datetime.now()
        changed: list[MemoryEntry] = []
        for entry in entries:
            if entry.rejected:
                continue
            last = entry.last_hit_at
            if last is not None and (now - last).total_seconds() < interval:
                continue  # 限频：同一记忆短期内只记一次命中，避免写放大
            entry.hot_score = min(10.0, float(entry.hot_score or 0) + boost)
            entry.hit_count = int(entry.hit_count or 0) + 1
            entry.last_hit_at = now
            changed.append(entry)
        if not changed:
            return 0
        await self.session.flush()
        # 热度参与重排权重，分区缓存需要失效，下一次召回才会用上新分数
        await self._bump_entries_scope(changed)
        return len(changed)

    @staticmethod
    def detect_feedback(text: str) -> str | None:
        """识别用户对上一轮模糊回忆的认可 / 否认。"""
        cleaned = (text or "").strip()
        if (not cleaned or len(cleaned) > 20 or is_overview_query(cleaned)
                or re.search(r"[？?]|(?:吗|么|呢)[。！!～~\s]*$", cleaned)):
            return None
        if CONFIRM_PATTERN.match(cleaned):
            return "confirm"
        if DENY_PATTERN.search(cleaned):
            return "deny"
        return None

    # ------------------------------------------------------------------
    # 管理 / 运维
    # ------------------------------------------------------------------
    async def list_entries(
        self,
        bot_id: str,
        user_id: str | None = None,
        *,
        page: int = 1,
        page_size: int = 20,
        scope_type: str | None = None,
        group_id: str | None = None,
        target_type: str | None = None,
        keyword: str | None = None,
        memory_type: str | None = None,
        rejected: bool | None = None,
        library_id: str | None = None,
    ) -> tuple[list[MemoryEntry], int]:
        return await self.repo.list_for_user(
            library_id or await self.resolve_bot_id(bot_id),
            user_id,
            scope_type=scope_type,
            group_id=group_id,
            target_type=target_type,
            keyword=keyword,
            memory_type=memory_type,
            rejected=rejected,
            limit=page_size,
            offset=(max(page, 1) - 1) * page_size,
        )

    async def get(self, entry_id: str) -> MemoryEntry:
        entry = await self.repo.get(entry_id)
        if not entry:
            raise NotFoundError("记忆不存在")
        return entry

    def _admin_content(self, content: str, *, generated_summary: bool = False) -> str:
        limit = 1200 if generated_summary else int(self.config.get("memory.max_entry_chars", 500))
        text = clean_text(content, limit + 1)
        if not text or (NOISE_PATTERN.search(text) and not generated_summary):
            raise ValidationError("请输入有效的记忆内容")
        if len(text) > limit:
            raise ValidationError(f"记忆内容不能超过 {limit} 字")
        return text

    async def create_entry(
        self, *, bot_id: str, user_id: str, scope_type: str, group_id: str | None,
        content: str, memory_type: str, tag_keywords: list[str],
        library_id: str | None = None,
    ) -> MemoryEntry:
        """后台创建记忆；scope 映射：
        private → 用户私聊分区；group → 用户×群分区；
        group_shared → 群共享分区（target_type=group）；global → 全局分区。
        """
        if scope_type == "group_shared":
            if not group_id:
                raise ValidationError("群共享记忆必须填写群号")
            target_type, target_id = "group", str(group_id)
        elif scope_type == "global":
            target_type, target_id, group_id = "global", "", None
        elif scope_type == "group":
            if not group_id:
                raise ValidationError("群聊记忆必须填写群号")
            if not user_id:
                raise ValidationError("群聊记忆必须填写用户 ID")
            target_type, target_id = "user", user_id
        else:
            if not user_id:
                raise ValidationError("私聊记忆必须填写用户 ID")
            target_type, target_id, group_id = "user", user_id, None
        entry = await self.add_memory(
            bot_id=bot_id, target_type=target_type, target_id=target_id,
            scope_type=scope_type if scope_type in {"private", "group", "global"} else "group",
            group_id=group_id, user_id=user_id,
            content=self._admin_content(content), memory_type=memory_type,
            category=memory_type, keywords=tag_keywords, confidence=1.0, importance=1.0,
            library_id=library_id,
        )
        if entry is None:
            raise ConflictError("相同范围内已存在相似记忆，请编辑已有记忆")
        return entry

    async def update_entry(
        self, entry_id: str, *, content: str, memory_type: str, tag_keywords: list[str],
    ) -> MemoryEntry:
        entry = await self.get(entry_id)
        generated_summary = entry.category == "conversation_summary" and str(entry.source_message_id or "").startswith("ctxsum_")
        entry.content = self._admin_content(content, generated_summary=generated_summary)
        entry.memory_type = memory_type
        entry.tag_keywords = tag_keywords
        await self.session.flush()
        try:
            await self.vector.add([entry.id], [entry.content], [metadata_from_entry(entry)])
        except Exception:  # noqa: BLE001 - 保留数据库更正，可通过重建索引恢复
            logger.warning("记忆更正已保存，向量索引同步失败：%s", entry.id, exc_info=True)
        await self._bump_entries_scope([entry])
        return entry

    async def delete(self, entry_id: str) -> None:
        entry = await self.get(entry_id)
        await self.repo.delete(entry)
        try:
            await self.vector.delete([entry_id])
        except Exception:  # noqa: BLE001
            logger.warning("向量索引删除失败：%s", entry_id)
        await self._bump_recall_cache(entry.bot_id, entry.target_type, entry.target_id)

    async def reset(
        self,
        bot_id: str,
        *,
        scope_type: str | None = None,
        group_id: str | None = None,
        library_id: str | None = None,
    ) -> int:
        from sqlalchemy import and_

        bot_id = library_id or await self.resolve_bot_id(bot_id)
        conditions = [MemoryEntry.bot_id == bot_id]
        if scope_type:
            conditions.append(MemoryEntry.scope_type == scope_type)
        if group_id:
            conditions.append(MemoryEntry.group_id == group_id)
        ids = await self.repo.ids_where(and_(*conditions))
        if ids:
            try:
                for start in range(0, len(ids), 500):
                    await self.vector.delete(ids[start : start + 500])
            except Exception:  # noqa: BLE001
                logger.warning("向量索引批量删除失败")
        count = await self.repo.delete_ids(ids)
        await self._invalidate_recall_cache()
        return count

    async def export(
        self, bot_id: str, user_id: str | None = None, *,
        scope_type: str | None = None, group_id: str | None = None,
        keyword: str | None = None, memory_type: str | None = None,
        rejected: bool | None = None,
        library_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return await export_entries(
            self.repo, library_id or await self.resolve_bot_id(bot_id), user_id, self._tier_of,
            scope_type=scope_type,
            group_id=group_id, keyword=keyword, memory_type=memory_type, rejected=rejected,
        )

    async def stats(self, bot_id: str | None = None, *, library_id: str | None = None) -> dict[str, Any]:
        return await memory_stats(
            self.repo,
            bot_id=library_id or (await self.resolve_bot_id(bot_id) if bot_id else None),
            tier_fn=self._tier_of,
            backend=self.vector.name,
            fuzzy_enabled=self.fuzzy_enabled,
            precise_threshold=self._number("memory.precise_threshold", 0.7),
            fuzzy_threshold=self._number("memory.fuzzy_threshold", 0.5),
        )

    # ------------------------------------------------------------------
    # 维护任务（实现见 memory_maintenance）
    # ------------------------------------------------------------------
    async def decay_all(self) -> int:
        count = await maintenance_decay(
            self.repo, self._number("memory.hot_decay", 0.92)
        )
        if count:
            # 热度参与重排分数；衰减后若继续命中旧召回缓存，排序会停留在
            # 衰减前，直到 TTL 过期。全局代际号一次失效所有分区缓存即可。
            await self._invalidate_recall_cache()
        return count

    async def dedupe_all(self, limit: int | None = None) -> int:
        batch = int(limit or self.config.get("memory.maintenance_batch", 500))
        count = await maintenance_dedupe(self.repo, self.vector, batch)
        if count:
            await self._invalidate_recall_cache()
        return count

    async def purge_cold(self, *, force: bool = False) -> int:
        count = await maintenance_purge(
            self.repo,
            self.vector,
            enabled=bool(self.config.get("memory.auto_purge_cold", False)),
            days=int(self.config.get("memory.cold_purge_days", 180)),
            hot_below=self._number("memory.cold_purge_hot_below", 0.5),
            batch=int(self.config.get("memory.maintenance_batch", 500)),
            force=force,
        )
        if count:
            await self._invalidate_recall_cache()
        return count

    async def gc_vectors(self) -> int:
        count = await maintenance_gc(self.repo, self.vector)
        if count:
            await self._invalidate_recall_cache()
        return count

    async def reindex(self, bot_id: str | None = None) -> int:
        if bot_id is not None:
            bot_id = await self.resolve_bot_id(bot_id)
        count = await maintenance_reindex(self.repo, self.vector, bot_id=bot_id)
        if count:
            await self._invalidate_recall_cache()
        return count

    # ------------------------------------------------------------------
    # 兼容旧接口
    # ------------------------------------------------------------------
    def build_prompt(self, entries: list[MemoryEntry], *, fuzzy: bool = False) -> str:
        hits = [RecallHit(entry=entry, similarity=1.0) for entry in entries]
        prompt, _included = compose_prompt(
            hits,
            MemoryMode.FUZZY.value if fuzzy else MemoryMode.PRECISE.value,
            int(self.config.get("memory.max_prompt_chars", 900)),
        )
        return prompt
