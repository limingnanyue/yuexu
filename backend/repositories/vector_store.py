"""向量检索存储：优先 Chroma，缺少依赖 / 初始化失败时降级为关键词检索。

设计要点（对应 4.5.5 / 4.5.7）：
- Metadata 强制携带 bot_id / target_type / target_id / rejected，检索前置过滤；
- Chroma 集合写入 HNSW 参数（construction_ef / search_ef），平衡速度与精度；
- 向量化统一走 ``embedding_provider``（builtin/onnx/api），写入与查询都显式
  传预计算向量，集合 metadata 记录 embedding 签名，签名变化自动重建索引；
- 抽象接口预留 Qdrant 等引擎，实现 ``VectorStore`` 并注册即可替换。
"""

from __future__ import annotations

import asyncio
import heapq
import math
from abc import ABC, abstractmethod
from collections import OrderedDict
from pathlib import Path
from typing import Any

from backend.common.logger import get_logger
from backend.common.utils import KeywordQuery, extract_query_keywords, keyword_idf
from backend.repositories.embedding_provider import (
    EMBEDDING_SIGNATURE_KEY,
    EmbeddingProvider,
    get_embedding_provider,
)

logger = get_logger("yuexu.vector")


class VectorStore(ABC):
    """向量存储抽象。"""

    name: str = "base"

    @abstractmethod
    async def add(
        self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]] | None = None
    ) -> None: ...

    @abstractmethod
    async def search(
        self, query: str, limit: int = 5, where: dict[str, Any] | None = None
    ) -> list[tuple[str, float]]: ...

    @abstractmethod
    async def delete(self, ids: list[str]) -> None: ...

    @abstractmethod
    async def clear(self) -> None: ...

    async def update_metadata(self, ids: list[str], metadata: dict[str, Any]) -> None:
        """更新向量元数据（确认 / 否认后同步 rejected 等字段）。"""
        return None

    async def prewarm(self) -> int:
        """启动时预加载索引（默认无操作），返回已加载条数。"""
        return 0

    async def list_ids(self, where: dict[str, Any] | None = None) -> list[str]:
        """列出索引中的全部 ID（可按 metadata 过滤），供 GC / 重建使用。"""
        return []

    async def count(self) -> int:
        return 0


class ChromaVectorStore(VectorStore):
    """Chroma 本地持久化向量库。"""

    name = "chroma"

    def __init__(
        self,
        persist_dir: str | Path,
        collection: str = "yuexu_memory",
        *,
        construction_ef: int = 128,
        search_ef: int = 48,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        import chromadb

        self._provider = embedding_provider or get_embedding_provider(None)  # type: ignore[arg-type]
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection,
            metadata={
                "hnsw:space": "cosine",
                "hnsw:construction_ef": int(construction_ef),
                "hnsw:search_ef": int(search_ef),
                EMBEDDING_SIGNATURE_KEY: self._provider.signature,
            },
        )
        # 旧集合（或换过 embedding）记录的签名与当前不一致时需要重建索引；
        # HNSW 参数仅集合首次创建时生效，重建后一并更新签名。
        existing = (self._collection.metadata or {}).get(EMBEDDING_SIGNATURE_KEY)
        self.embedding_signature = str(existing) if existing else ""
        if self.embedding_signature and self.embedding_signature != self._provider.signature:
            logger.warning(
                "向量库 embedding 签名不一致（%s -> %s），需要重建索引",
                self.embedding_signature, self._provider.signature,
            )
        logger.info(
            "Chroma 向量库已加载：%s（collection=%s, search_ef=%s, embedding=%s）",
            persist_dir, collection, search_ef, self._provider.name,
        )

    @property
    def needs_reindex(self) -> bool:
        return self.embedding_signature != self._provider.signature

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        return await self._provider.embed(texts)

    async def add(
        self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]] | None = None
    ) -> None:
        if not ids:
            return
        embeddings = await self._embed(documents)
        await asyncio.to_thread(
            self._collection.upsert,
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas or [{} for _ in ids],
        )

    async def search(
        self, query: str, limit: int = 5, where: dict[str, Any] | None = None
    ) -> list[tuple[str, float]]:
        if not query:
            return []
        embedding = (await self._embed([query]))[0]
        result = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=[embedding],
            n_results=max(1, limit),
            where=self._to_chroma_where(where),
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        scores: list[tuple[str, float]] = []
        for index, item_id in enumerate(ids):
            distance = float(distances[index]) if index < len(distances) else 1.0
            scores.append((str(item_id), self._provider.calibrate(1.0 - distance)))
        return scores

    async def update_metadata(self, ids: list[str], metadata: dict[str, Any]) -> None:
        if not ids:
            return
        await asyncio.to_thread(
            self._collection.update,
            ids=ids,
            metadatas=[dict(metadata) for _ in ids],
        )

    async def mark_reindexed(self) -> None:
        """索引重建完成后更新集合签名，结束「待重建」状态。"""
        metadata = dict(self._collection.metadata or {})
        metadata[EMBEDDING_SIGNATURE_KEY] = self._provider.signature
        await asyncio.to_thread(self._collection.modify, metadata=metadata)
        self.embedding_signature = self._provider.signature
        logger.info("向量库 embedding 签名已更新：%s", self._provider.signature)

    async def delete(self, ids: list[str]) -> None:
        if ids:
            await asyncio.to_thread(self._collection.delete, ids=ids)

    async def clear(self) -> None:
        name = self._collection.name
        await asyncio.to_thread(self._client.delete_collection, name)
        self._collection = self._client.get_or_create_collection(
            name=name,
            metadata={
                "hnsw:space": "cosine",
                "hnsw:construction_ef": 128,
                "hnsw:search_ef": 48,
                EMBEDDING_SIGNATURE_KEY: self._provider.signature,
            },
        )
        # 清空后的索引为空集，视为已对齐当前向量空间
        self.embedding_signature = self._provider.signature

    async def list_ids(self, where: dict[str, Any] | None = None) -> list[str]:
        result = await asyncio.to_thread(
            self._collection.get, include=[], where=self._to_chroma_where(where)
        )
        return [str(item) for item in result.get("ids") or []]

    async def count(self) -> int:
        return int(await asyncio.to_thread(self._collection.count))

    @staticmethod
    def _to_chroma_where(where: dict[str, Any] | None) -> dict[str, Any] | None:
        if not where:
            return None
        clauses = [
            {key: value}
            for key, value in where.items()
            if value is not None and value != ""
        ]
        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}


class KeywordVectorStore(VectorStore):
    """关键词降级实现：向量库不可用时保证记忆检索仍可用。"""

    name = "keyword"

    def __init__(self, repo: Any) -> None:
        self._repo = repo

    async def add(self, ids, documents, metadatas=None) -> None:  # noqa: ANN001
        # 数据已由 MemoryRepo 落库，无需额外索引
        return None

    async def search(
        self, query: str, limit: int = 5, where: dict[str, Any] | None = None
    ) -> list[tuple[str, float]]:
        where = where or {}
        bot_id = str(where.get("bot_id") or "")
        if not bot_id or not query:
            return []
        # 词法口径与 MemoryService 的关键词兜底 / 模糊双路召回保持一致：
        # 内容二字词优先（extract_query_keywords），长句尾部的专名也能进入
        # SQL LIKE 候选圈选。旧实现用「少量代表性标签」（extract_keywords
        # limit=8），与主链路的打分口径不一致，降级时召回质量会额外缩水。
        keywords = extract_query_keywords(query, limit=12)
        if not keywords:
            return []
        rows = await self._repo.search_candidates(
            bot_id,
            keywords,
            target_type=str(where.get("target_type") or "user"),
            target_id=str(where.get("target_id") or ""),
            user_id=str(where.get("user_id") or "") or None,
            group_id=str(where.get("group_id") or "") or None,
            scope_type=str(where.get("scope_type") or "") or None,
            limit=limit * 4,
        )
        scored: list[tuple[str, float]] = []
        # 与 MemoryService 的模糊 / 兜底召回共用同一套关键词打分：
        # 字符并集覆盖率 + 候选集 IDF。旧实现按「命中个数 / 3」，
        # 一个四字词会连带命中多个 2/3 字子串，容易被算成 1.0——
        # 写入查重时曾把「我住在北京」与「我住在杭州」误判为重复。
        # 查询剖析只构造一次，候选循环里只做「关键词是否出现」的判定。
        idf = keyword_idf((row.content or "" for row in rows), keywords)
        profile = KeywordQuery(query, keywords, idf=idf)
        for row in rows:
            score = profile.score(row.content or "")
            if score > 0:
                scored.append((row.id, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    async def delete(self, ids: list[str]) -> None:
        return None

    async def clear(self) -> None:
        return None


class BuiltinVectorStore(VectorStore):
    """零依赖内存向量存储：TF-IDF 中文语义检索（默认引擎）。

    - builtin provider 支持稀疏 token 权重时走 **TF-IDF 精确余弦**：
      词频 × 语料级逆文档频率（IDF 在本库全部记忆上动态统计）——
      区分度高的 token（「火锅」「橘猫」）权重放大，条条记忆都有的
      通用 token（「我」「喜欢」）权重压缩，Top-N 排序更准；
    - **每条记忆的 IDF 加权归一化向量按代际惰性缓存**：候选打分只需
      按查询 token（≤ ``_QUERY_TOKEN_LIMIT`` 个）查点积，复杂度与条目
      长度无关，写入 / 删除改变 IDF 分布时自动重算；
    - **倒排索引候选裁剪**：只评分与查询共享高权重 token 的记忆，
      分区记忆量再大也不做无效全扫；
    - 向量化统一走 ``embedding_provider``（builtin/onnx/api 均可驱动，
      稀疏路径仅 builtin；onnx/api 走稠密点积）；
    - 进程内缓存，首次检索/写入时从数据库全量加载重建（确定性零成本）；
    - 检索按 where 条件（bot / target / user / group / rejected）预过滤，
      分区隔离口径与 Chroma 引擎一致。
    """

    name = "builtin"

    _LOAD_BATCH = 200
    _QUERY_CACHE_SIZE = 256
    # 查询侧只保留 IDF 加权后权重最高的 N 个 token（降噪 + 提速）
    _QUERY_TOKEN_LIMIT = 12

    def __init__(self, repo: Any, provider: EmbeddingProvider | None = None) -> None:
        self._repo = repo
        self._provider = provider or get_embedding_provider()
        self._sparse = hasattr(self._provider, "sparse_embed")
        # 值为稀疏 token 权重 dict（builtin）或稠密 list[float]（onnx/api）
        self._vectors: dict[str, Any] = {}
        self._metadatas: dict[str, dict[str, Any]] = {}
        # 分区桶索引：检索从 O(全局) 降到 O(本分区)，记忆量增长后仍稳定
        self._buckets: dict[tuple[str, str, str], set[str]] = {}
        # 倒排索引（token → 记忆 id）与文档频率（token → 出现条数）：
        # 候选裁剪与 IDF 统计共用，随写入 / 删除实时维护
        self._postings: dict[str, set[str]] = {}
        self._df: dict[str, int] = {}
        # IDF 记忆化：语料规模不变期间同一 token 的 IDF 恒定，
        # 候选打分的逐 token 幂运算退化为字典查询（写入 / 删除时整体失效）
        self._idf_memo: dict[str, float] = {}
        # IDF 代际号：与 _idf_memo 同步失效（写入 / 删除时递增）。用于惰性
        # 缓存的「每条记忆 IDF 加权归一化向量」——缓存的向量依赖全库 IDF，
        # 代际不匹配即过期，会在下次打分时按当前 IDF 重算。
        self._idf_gen = 0
        # item_id → (idf 代际, IDF 加权且 L2 归一化的稀疏向量)。打分时只需
        # 遍历查询 token（≤ _QUERY_TOKEN_LIMIT 个）在该向量里查点积，复杂度
        # 从 O(条目词数) 降到 O(查询词数)；长记忆（数百 token）批量打分时
        # 收益最明显。原始 TF 向量仍存于 _vectors，供代际过期后重算。
        self._weighted: dict[str, tuple[int, dict[str, float]]] = {}
        # 查询向量 LRU：多轮对话中相似提问不必重复向量化
        self._query_cache: OrderedDict[str, Any] = OrderedDict()
        self._loaded = False
        self._load_lock = asyncio.Lock()

    @staticmethod
    def _bucket_of(metadata: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(metadata.get("bot_id") or ""),
            str(metadata.get("target_type") or ""),
            str(metadata.get("target_id") or ""),
        )

    def _index(self, item_id: str, metadata: dict[str, Any], vector: Any = None) -> None:
        self._buckets.setdefault(self._bucket_of(metadata), set()).add(item_id)
        if isinstance(vector, dict):
            for token in vector:
                self._df[token] = self._df.get(token, 0) + 1
                self._postings.setdefault(token, set()).add(item_id)

    def _unindex(self, item_id: str) -> None:
        metadata = self._metadatas.get(item_id) or {}
        bucket = self._buckets.get(self._bucket_of(metadata))
        if bucket is not None:
            bucket.discard(item_id)
        vector = self._vectors.get(item_id)
        if isinstance(vector, dict):
            for token in vector:
                count = self._df.get(token, 0) - 1
                if count > 0:
                    self._df[token] = count
                else:
                    self._df.pop(token, None)
                ids = self._postings.get(token)
                if ids is not None:
                    ids.discard(item_id)
                    if not ids:
                        del self._postings[token]

    def _idf(self, token: str) -> float:
        """平滑 IDF：条条记忆都有的 token 权重趋近 1，独有 token 权重最大。"""
        cached = self._idf_memo.get(token)
        if cached is not None:
            return cached
        value = math.log((len(self._vectors) + 1) / (self._df.get(token, 0) + 1)) + 1.0
        self._idf_memo[token] = value
        return value

    def _invalidate_idf_cache(self) -> None:
        """语料 / 文档频率变化：整体失效 IDF 记忆化，并递增加权向量代际。"""
        self._idf_memo.clear()
        self._idf_gen += 1

    def _weighted_of(self, item_id: str) -> dict[str, float] | None:
        """条目的 IDF 加权归一化向量（惰性计算，按代际缓存）。

        打分公式 ``dot(q, e) / (|q|·|e|)`` 中 ``e/|e|`` 只依赖条目自身与当前
        全库 IDF：预先归一化缓存后，每个候选的打分只需对查询 token（有限
        个）做点积。代际不匹配（写入 / 删除改变了 IDF 分布）时按当前 IDF
        重算一次并回填。
        """
        cached = self._weighted.get(item_id)
        if cached is not None and cached[0] == self._idf_gen:
            return cached[1]
        raw = self._vectors.get(item_id)
        if not isinstance(raw, dict):
            return None
        weighted: dict[str, float] = {}
        norm2 = 0.0
        for token, weight in raw.items():
            term = weight * self._idf(token)
            norm2 += term * term
            weighted[token] = term
        norm = math.sqrt(norm2)
        if norm > 0.0:
            inverse = 1.0 / norm
            for token in weighted:
                weighted[token] *= inverse
        self._weighted[item_id] = (self._idf_gen, weighted)
        return weighted

    def _bind_repo(self, repo: Any) -> None:
        """进程级单例跨会话复用：每次创建时刷新绑定的当前会话 repo。"""
        if repo is not None:
            self._repo = repo

    async def _embed_many(self, texts: list[str]) -> list[Any]:
        if self._sparse:
            return [self._provider.sparse_embed(text) for text in texts]
        return await self._provider.embed(texts)

    async def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            repo = self._repo
            iter_entries = getattr(repo, "iter_entries", None)
            if iter_entries is not None:
                total = 0
                async for rows in iter_entries(self._LOAD_BATCH):
                    vectors = await self._embed_many(
                        [entry.content or "" for entry in rows]
                    )
                    for entry, vector in zip(rows, vectors):
                        self._vectors[entry.id] = vector
                        self._metadatas[entry.id] = self._metadata_of(entry)
                        self._index(entry.id, self._metadatas[entry.id], vector)
                    total += len(rows)
                    await asyncio.sleep(0)
                logger.info(
                    "内置向量库已从数据库加载：%s 条（provider=%s, %s）",
                    total, self._provider.name,
                    "sparse" if self._sparse else "dense",
                )
            self._loaded = True

    async def prewarm(self) -> int:
        """启动时预加载全量记忆索引，首条消息不再承担加载延迟（防首查超时降级）。"""
        await self._ensure_loaded()
        return len(self._vectors)

    @staticmethod
    def _metadata_of(entry: Any) -> dict[str, Any]:
        return {
            "bot_id": entry.bot_id,
            "target_type": entry.target_type,
            "target_id": entry.target_id,
            "scope_type": entry.scope_type,
            "user_id": entry.user_id,
            "group_id": entry.group_id or "",
            "memory_type": entry.memory_type,
            "rejected": bool(entry.rejected),
        }

    @staticmethod
    def _active_where(where: dict[str, Any] | None) -> dict[str, Any]:
        return {
            key: value for key, value in (where or {}).items()
            if value is not None and value != ""
        }

    async def add(
        self, ids: list[str], documents: list[str], metadatas: list[dict[str, Any]] | None = None
    ) -> None:
        if not ids:
            return
        await self._ensure_loaded()
        vectors = await self._embed_many(documents)
        self._invalidate_idf_cache()  # 语料规模 / 文档频率即将变化
        for index, item_id in enumerate(ids):
            self._unindex(item_id)  # 用旧向量回退 df / 倒排
            self._weighted.pop(item_id, None)  # 旧加权向量随新语料失效
            metadata = dict((metadatas or [{}] * len(ids))[index])
            self._vectors[item_id] = vectors[index]
            self._metadatas[item_id] = metadata
            self._index(item_id, metadata, vectors[index])

    def _dense_score(self, query_vector: Any, entry_vector: Any) -> float:
        # 稠密向量均已 L2 归一化，点积即余弦（onnx / api provider）
        raw = sum(a * b for a, b in zip(query_vector, entry_vector))
        return self._provider.calibrate(raw)

    async def _query_vector(self, query: str) -> Any:
        cached = self._query_cache.get(query)
        if cached is not None:
            self._query_cache.move_to_end(query)
            return cached
        vector = (await self._embed_many([query]))[0]
        self._query_cache[query] = vector
        while len(self._query_cache) > self._QUERY_CACHE_SIZE:
            self._query_cache.popitem(last=False)
        return vector

    def _candidate_tokens(self, weighted: dict[str, float]) -> dict[str, float]:
        """挑选用于倒排候选圈选的查询 token，避免被“我 / 的”这类泛词拖垮。

        查询向量里每个 token 都参与最终打分，但圈选候选时只需要少量高区分
        度 token：一个出现在 60% 以上记忆里的词，几乎不能缩小候选集，反而
        会把整个分区倒排表并进来。这里按权重排序，跳过文档频率过高的词；
        如果查询全是泛词，则退回权重最高的 3 个，保证仍有结果。

        对 2000 条记忆的基准测试，这一步把“我”这类 token 的候选集从全表
        降到真正的主题词候选，同时不改变候选记忆的最终余弦排序。
        """
        if not weighted:
            return {}
        ranked = sorted(weighted.items(), key=lambda item: item[1], reverse=True)
        total = len(self._vectors)
        if total <= 8:
            return dict(ranked[: self._QUERY_TOKEN_LIMIT])
        common_cutoff = max(8, int(total * 0.6))
        informative = [
            (token, weight) for token, weight in ranked
            if self._df.get(token, 0) <= common_cutoff
        ]
        if not informative:
            informative = ranked[:3]
        return dict(informative[: self._QUERY_TOKEN_LIMIT])

    async def search(
        self, query: str, limit: int = 5, where: dict[str, Any] | None = None
    ) -> list[tuple[str, float]]:
        if not query:
            return []
        await self._ensure_loaded()
        clauses = self._active_where(where)
        # 分桶路由：where 含分区三要素时只扫本分区，否则全量
        bucket_key = (
            str(clauses.get("bot_id") or ""),
            str(clauses.get("target_type") or ""),
            str(clauses.get("target_id") or ""),
        )
        partition_ids: set[str] | None = None
        # global 分区的 target_id 合法为空串；旧条件只看 target_id，导致全局
        # 记忆每次都退化为全库扫描。target_type=global 时允许空 ID 走分桶。
        if bucket_key[0] and (bucket_key[2] or bucket_key[1] == "global"):
            partition_ids = self._buckets.get(bucket_key)
            if not partition_ids:
                return []

        if self._sparse:
            # 查询 IDF 加权 + top-K 截断（降噪提速）
            query_raw = await self._query_vector(query)
            weighted = {
                token: weight * self._idf(token)
                for token, weight in query_raw.items()
            }
            if len(weighted) > self._QUERY_TOKEN_LIMIT:
                weighted = dict(
                    sorted(weighted.items(), key=lambda item: item[1], reverse=True)[
                        : self._QUERY_TOKEN_LIMIT
                    ]
                )
            query_norm = math.sqrt(sum(value * value for value in weighted.values()))
            if query_norm <= 0.0:
                return []
            # 倒排候选裁剪：只从高区分度 token 取候选。最终打分仍使用完整
            # weighted（包含泛词），因此不会漏掉“主题词 + 泛词”共同命中的
            # 记忆；这里只是不把全表都拉进评分循环。
            candidate_weighted = self._candidate_tokens(weighted)
            candidates: set[str] = set()
            for token in candidate_weighted:
                ids = self._postings.get(token)
                if ids:
                    candidates.update(ids)
            if partition_ids is not None:
                candidates &= partition_ids
            scored: list[tuple[str, float]] = []
            for item_id in candidates:
                metadata = self._metadatas.get(item_id) or {}
                if any(metadata.get(key) != value for key, value in clauses.items()):
                    continue
                entry_weighted = self._weighted_of(item_id)
                if not entry_weighted:
                    continue
                # 归一化条目向量 + 查询侧范数：余弦只需按查询 token 查点积
                dot = 0.0
                for token, query_term in weighted.items():
                    entry_term = entry_weighted.get(token)
                    if entry_term is not None:
                        dot += query_term * entry_term
                if dot <= 0.0:
                    continue
                scored.append((item_id, self._provider.calibrate(dot / query_norm)))
        else:
            query_vector = await self._query_vector(query)
            ids_iter = (
                iter(partition_ids) if partition_ids is not None else self._vectors
            )
            scored = []
            for item_id in ids_iter:
                entry_vector = self._vectors.get(item_id)
                if entry_vector is None:
                    continue
                metadata = self._metadatas.get(item_id) or {}
                if any(metadata.get(key) != value for key, value in clauses.items()):
                    continue
                scored.append((item_id, self._dense_score(query_vector, entry_vector)))
        # Top-K 用堆而不是整表排序：候选集可能有上万条，O(n·log k) 只保留前 k
        # （k = limit）比 O(n·log n) 全排序快，且与「稳定降序取前 k」的结果一致
        # （``nlargest`` 等价于 ``sorted(..., key=分数, reverse=True)[:k]``）。
        return heapq.nlargest(
            max(1, limit), scored, key=lambda item: item[1]
        )

    async def update_metadata(self, ids: list[str], metadata: dict[str, Any]) -> None:
        bucket_fields = {"bot_id", "target_type", "target_id"}
        for item_id in ids:
            old = self._metadatas.get(item_id)
            if old is None:
                continue
            if bucket_fields & set(metadata):
                self._unindex(item_id)
                old.update(metadata)
                self._index(item_id, old)
            else:
                old.update(metadata)

    async def delete(self, ids: list[str]) -> None:
        self._invalidate_idf_cache()  # 语料规模 / 文档频率即将变化
        for item_id in ids:
            self._unindex(item_id)  # 同步回退分桶 / df / 倒排
            self._weighted.pop(item_id, None)  # 条目级加权向量随之删除
            self._vectors.pop(item_id, None)
            self._metadatas.pop(item_id, None)

    async def clear(self) -> None:
        self._vectors.clear()
        self._metadatas.clear()
        self._buckets.clear()
        self._postings.clear()
        self._df.clear()
        self._invalidate_idf_cache()
        self._weighted.clear()
        self._query_cache.clear()
        self._loaded = True  # 清空后不自动回读数据库

    async def list_ids(self, where: dict[str, Any] | None = None) -> list[str]:
        await self._ensure_loaded()
        clauses = self._active_where(where)
        return [
            item_id for item_id, metadata in self._metadatas.items()
            if all(metadata.get(key) == value for key, value in clauses.items())
        ]

    async def count(self) -> int:
        await self._ensure_loaded()
        return len(self._vectors)


_chroma_store: VectorStore | None = None
_chroma_failed = False
_builtin_store: BuiltinVectorStore | None = None


def create_vector_store(config, repo: Any) -> VectorStore:  # noqa: ANN001
    """按配置创建向量存储，失败时逐级降级。

    引擎优先级：chroma（需安装 chromadb）→ builtin（零依赖内存向量）→
    keyword（SQL LIKE）。进程内复用同一实例；keyword 依赖当前会话按需创建。
    """
    global _chroma_store, _chroma_failed, _builtin_store
    backend = str(config.get("memory.backend", "builtin")).lower()
    if backend == "chroma" and not _chroma_failed:
        if _chroma_store is not None:
            return _chroma_store
        try:
            persist_dir = config.resolve_path(
                str(config.get("memory.chroma_dir", "data/chroma_db"))
            )
            _chroma_store = ChromaVectorStore(
                persist_dir,
                str(config.get("memory.chroma_collection", "yuexu_memory")),
                construction_ef=int(config.get("memory.hnsw_construction_ef", 128)),
                search_ef=int(config.get("memory.hnsw_search_ef", 48)),
                embedding_provider=get_embedding_provider(config),
            )
            return _chroma_store
        except Exception as exc:  # noqa: BLE001 - 缺少依赖 / 初始化失败
            _chroma_failed = True
            logger.warning(
                "Chroma 初始化失败（%s），降级为内置零依赖向量检索（builtin）", exc
            )
    elif backend == "qdrant":
        # Qdrant 通过 VectorStore 接口扩展接入；当前先降级保证可用性
        logger.warning("Qdrant 引擎尚未内置，使用内置零依赖向量检索（builtin）")
    if backend != "keyword":
        if _builtin_store is None:
            _builtin_store = BuiltinVectorStore(repo, get_embedding_provider(config))
        else:
            _builtin_store._bind_repo(repo)
        return _builtin_store
    return KeywordVectorStore(repo)


def reset_vector_store_cache() -> None:
    """测试 / 配置切换时重置缓存。"""
    global _chroma_store, _chroma_failed, _builtin_store
    _chroma_store = None
    _chroma_failed = False
    _builtin_store = None
