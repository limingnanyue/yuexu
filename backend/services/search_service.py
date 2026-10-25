"""DeepSeek 联网搜索（开发文档 4.8）：独立解耦，失败自动跳过，不阻断对话。"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.constants import SearchTrigger
from backend.common.logger import get_logger
from backend.common.utils import truncate
from backend.core.config_loader import get_config
from backend.repositories.log_repo import LogRepo

logger = get_logger("yuexu.service.search")


@dataclass
class SearchItem:
    title: str = ""
    url: str = ""
    snippet: str = ""


@dataclass
class SearchResult:
    success: bool
    query: str = ""
    provider: str = "deepseek"
    summary: str = ""
    items: list[SearchItem] = field(default_factory=list)
    latency_ms: int = 0
    error: str | None = None


class SearchProvider(ABC):
    """搜索源抽象：后续替换 Bing / Bocha 等只需实现本接口。"""

    name: str = "base"

    @abstractmethod
    async def search(self, query: str, *, top_k: int, timeout: float) -> SearchResult:
        ...


class DeepSeekSearchProvider(SearchProvider):
    """DeepSeek Search API 客户端（端点可配置，兼容不同版本的搜索接口）。"""

    name = "deepseek"

    def __init__(
        self,
        *,
        base_url: str,
        endpoint: str,
        api_key: str,
        max_summary_chars: int = 1500,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        self.api_key = api_key
        self.max_summary_chars = max_summary_chars

    async def search(self, query: str, *, top_k: int, timeout: float) -> SearchResult:
        if not self.api_key:
            return SearchResult(success=False, query=query, provider=self.name, error="未配置搜索 API Key")

        url = f"{self.base_url}{self.endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"query": query, "top_k": top_k, "max_results": top_k}
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                return SearchResult(
                    success=False, query=query, provider=self.name, latency_ms=latency_ms,
                    error=f"搜索接口返回 {response.status_code}：{truncate(response.text, 200)}",
                )
            data = response.json()
            items = self._extract_items(data)
            summary = self._build_summary(items, data)
            return SearchResult(
                success=True,
                query=query,
                provider=self.name,
                summary=summary,
                items=items,
                latency_ms=latency_ms,
            )
        except httpx.TimeoutException:
            return SearchResult(
                success=False, query=query, provider=self.name,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error="搜索请求超时",
            )
        except (httpx.HTTPError, ValueError) as exc:
            return SearchResult(
                success=False, query=query, provider=self.name,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=f"搜索请求失败：{exc}",
            )

    def _extract_items(self, data: dict[str, Any]) -> list[SearchItem]:
        raw_items: Any = (
            data.get("results")
            or data.get("items")
            or data.get("web_pages")
            or data.get("pages")
            or []
        )
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("value") or raw_items.get("list") or []
        items: list[SearchItem] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            items.append(
                SearchItem(
                    title=str(raw.get("title") or raw.get("name") or ""),
                    url=str(raw.get("url") or raw.get("link") or ""),
                    snippet=str(
                        raw.get("snippet") or raw.get("summary") or raw.get("content")
                        or raw.get("text") or ""
                    ),
                )
            )
        return items

    def _build_summary(self, items: list[SearchItem], data: dict[str, Any]) -> str:
        answer = data.get("answer") or data.get("summary")
        if isinstance(answer, str) and answer.strip():
            return truncate(answer.strip(), self.max_summary_chars)
        lines: list[str] = []
        for index, item in enumerate(items, start=1):
            if not (item.title or item.snippet):
                continue
            line = f"{index}. {item.title}：{truncate(item.snippet, 300)}"
            if item.url:
                line += f"（{item.url}）"
            lines.append(line)
        return truncate("\n".join(lines), self.max_summary_chars)


class SearchService:
    """联网搜索服务：触发判断、调用、日志、Prompt 参考文本。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.config = get_config()
        self.log_repo = LogRepo(session)

    # ------------------------------------------------------------------
    # 开关 / 触发
    # ------------------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.config.get("search.api_key")) and bool(self.config.get("search.enabled"))

    def is_enabled(self, account_settings: dict | None = None, group_rule=None) -> bool:  # noqa: ANN001
        if not self.config.get("search.enabled"):
            return False
        if not self.config.get("search.api_key"):
            return False
        if account_settings and account_settings.get("search") is False:
            return False
        if group_rule is not None and getattr(group_rule, "enabled_search", True) is False:
            return False
        return True

    def should_search(self, text: str, account_settings: dict | None = None, group_rule=None) -> bool:  # noqa: ANN001
        """自动识别时效类问题。"""
        if not self.is_enabled(account_settings, group_rule):
            return False
        if not self.config.get("search.auto_trigger", True):
            return False
        if not text or len(text.strip()) < 4:
            return False
        keywords = self.config.get("search.freshness_keywords", []) or []
        if any(keyword in text for keyword in keywords):
            return True
        return any(token in text for token in ("?", "？"))

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------
    async def search(
        self,
        query: str,
        *,
        trigger_mode: str = SearchTrigger.AUTO.value,
        bot_id: str = "",
        user_id: str = "",
    ) -> SearchResult:
        provider = self._build_provider()
        timeout = float(self.config.get("search.timeout", 15))
        top_k = int(self.config.get("search.top_k", 5))
        result = await provider.search(query, top_k=top_k, timeout=timeout)

        await self.log_repo.add_search(
            bot_id=bot_id,
            user_id=user_id,
            query=truncate(query, 200),
            provider=provider.name,
            trigger_mode=trigger_mode,
            result_count=len(result.items),
            latency_ms=result.latency_ms,
            success=result.success,
            error=result.error,
            summary_preview=truncate(result.summary, 500),
        )
        if result.success:
            logger.info("联网搜索完成：%s（%s 条）", truncate(query, 40), len(result.items))
        else:
            logger.warning("联网搜索失败：%s", result.error)
        return result

    async def build_reference(self, result: SearchResult) -> str:
        """把搜索结果整理为注入 LLM 的参考资料文本。"""
        if not result.success or not result.summary:
            return ""
        return (
            "以下是与当前问题相关的联网搜索资料，可作为事实参考；"
            "若资料与对话无关请忽略，不要直接复述来源链接：\n"
            f"{result.summary}"
        )

    # ------------------------------------------------------------------
    def _build_provider(self) -> SearchProvider:
        name = str(self.config.get("search.provider", "deepseek"))
        if name == "deepseek":
            return DeepSeekSearchProvider(
                base_url=str(self.config.get("search.base_url", "https://api.deepseek.com")),
                endpoint=str(self.config.get("search.endpoint", "/v1/search")),
                api_key=str(self.config.get("search.api_key", "")),
                max_summary_chars=int(self.config.get("search.max_summary_chars", 1500)),
            )
        raise ValueError(f"未知搜索服务商：{name}")
