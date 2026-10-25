"""限流风控（开发文档 4.12）：消息 / 语音 / 推送分开限流，随机延时。"""

from __future__ import annotations

from backend.common.cache import CacheBackend
from backend.common.constants import (
    push_daily_key,
    rate_account_key,
    rate_group_key,
    rate_user_key,
)
from backend.common.logger import get_logger
from backend.common.utils import human_delay
from backend.core.config_loader import get_config
from backend.core.runtime import get_cache

logger = get_logger("yuexu.service.rate_limit")


class RateLimitService:
    """基于缓存的固定窗口限流。"""

    def __init__(self, cache: CacheBackend | None = None) -> None:
        self.config = get_config()
        self.cache = cache or get_cache()

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("rate_limit.enabled", True))

    @property
    def window(self) -> int:
        return max(1, int(self.config.get("redis.rate_window", 60)))

    # ------------------------------------------------------------------
    # 对话消息
    # ------------------------------------------------------------------
    async def check_message(self, event) -> tuple[bool, str]:  # noqa: ANN001 - BotEvent
        if not self.enabled:
            return True, ""

        user_limit = int(self.config.get("rate_limit.per_user_per_minute", 12))
        user_used = await self.cache.incr(rate_user_key(event.bot_id, event.user_id), ttl=self.window)
        if user_used > user_limit:
            return False, f"用户消息频率超限（{user_used}/{user_limit}）"

        if event.is_group and event.group_id:
            group_limit = int(self.config.get("rate_limit.per_group_per_minute", 40))
            group_used = await self.cache.incr(
                rate_group_key(event.bot_id, str(event.group_id)), ttl=self.window
            )
            if group_used > group_limit:
                return False, f"群消息频率超限（{group_used}/{group_limit}）"

        account_limit = int(self.config.get("rate_limit.per_account_per_minute", 60))
        account_used = await self.cache.incr(rate_account_key(event.bot_id), ttl=self.window)
        if account_used > account_limit:
            return False, f"账号消息频率超限（{account_used}/{account_limit}）"

        return True, ""

    # ------------------------------------------------------------------
    # 自动推送
    # ------------------------------------------------------------------
    async def check_push(
        self, bot_id: str, task_id: str, daily_limit: int = 0
    ) -> tuple[bool, str]:
        if not self.enabled:
            return True, ""

        push_limit = int(self.config.get("rate_limit.push_per_minute", 5))
        used = await self.cache.incr(f"rate:push:{bot_id}", ttl=self.window)
        if used > push_limit:
            return False, f"推送频率超限（{used}/{push_limit}）"

        hard_daily_limit = int(self.config.get("rate_limit.push_daily_limit", 50))
        effective_limit = min(
            [limit for limit in (daily_limit, hard_daily_limit) if limit > 0] or [0]
        )
        if effective_limit > 0:
            daily_used = await self.cache.incr(push_daily_key(task_id), ttl=86400)
            if daily_used > effective_limit:
                return False, f"单日推送次数超限（{daily_used}/{effective_limit}）"
        return True, ""

    # ------------------------------------------------------------------
    # 随机延时
    # ------------------------------------------------------------------
    async def random_delay(self, *, stricter: bool = False) -> float:
        """发送前随机等待，降低风控概率。"""
        low = float(self.config.get("rate_limit.random_delay_min", 0.3))
        high = float(self.config.get("rate_limit.random_delay_max", 1.2))
        if stricter:
            low *= 1.5
            high *= 2.0
        return await human_delay(low, high)
