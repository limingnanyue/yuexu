"""群组管理（开发文档 4.3）：欢迎语、退群提示、黑名单、屏蔽词、防刷屏、禁言。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.base_adapter import BaseAdapter, SendResult
from backend.common.cache import CacheBackend
from backend.common.exceptions import NotFoundError, ValidationError
from backend.common.logger import get_logger
from backend.core.config_loader import get_config
from backend.core.runtime import get_cache
from backend.database.models import GroupRule
from backend.repositories.group_rule_repo import GroupRuleRepo

logger = get_logger("yuexu.service.group")


class GroupAdminService:
    """单群规则与群管理能力。"""

    def __init__(self, session: AsyncSession, cache: CacheBackend | None = None) -> None:
        self.session = session
        self.repo = GroupRuleRepo(session)
        self.cache = cache or get_cache()
        self.config = get_config()

    # ------------------------------------------------------------------
    # 规则查询 / 管理
    # ------------------------------------------------------------------
    async def get_rule(self, bot_id: str, group_id: str) -> GroupRule | None:
        return await self.repo.get_rule(bot_id, group_id)

    async def list_page(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        bot_id: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[GroupRule], int]:
        rules = await self.repo.all(bot_id=bot_id) if bot_id else await self.repo.all()
        if keyword:
            lowered = keyword.lower()
            rules = [
                rule for rule in rules
                if lowered in rule.group_id.lower() or lowered in (rule.group_name or "").lower()
            ]
        total = len(rules)
        start = max(page - 1, 0) * page_size
        return rules[start : start + page_size], total

    async def get(self, rule_id: str) -> GroupRule:
        rule = await self.repo.get(rule_id)
        if not rule:
            raise NotFoundError("群规则不存在")
        return rule

    async def create(self, data: dict[str, Any]) -> GroupRule:
        payload = self._clean_payload(data, creating=True)
        existing = await self.repo.first(bot_id=payload.get("bot_id"), group_id=payload["group_id"])
        if existing:
            raise ValidationError("该群规则已存在，请直接编辑")
        return await self.repo.create(**payload)

    async def update(self, rule_id: str, data: dict[str, Any]) -> GroupRule:
        rule = await self.get(rule_id)
        return await self.repo.update(rule, **self._clean_payload(data, creating=False))

    async def delete(self, rule_id: str) -> None:
        rule = await self.get(rule_id)
        await self.repo.delete(rule)

    async def ensure_rule(self, bot_id: str, group_id: str, group_name: str = "") -> GroupRule:
        rule = await self.get_rule(bot_id, group_id)
        if rule:
            if group_name and not rule.group_name:
                rule.group_name = group_name
                await self.session.flush()
            return rule
        return await self.repo.create(
            bot_id=bot_id, group_id=group_id, group_name=group_name
        )

    # ------------------------------------------------------------------
    # 入站过滤
    # ------------------------------------------------------------------
    async def is_blacklisted(self, rule: GroupRule | None, user_id: str) -> bool:
        if not rule:
            return False
        return str(user_id) in {str(item) for item in (rule.blacklist or [])}

    async def match_block_word(self, rule: GroupRule | None, text: str) -> str | None:
        if not rule or not text:
            return None
        lowered = text.lower()
        for word in rule.block_words or []:
            word = str(word).strip()
            if word and word.lower() in lowered:
                return word
        return None

    async def anti_flood(
        self, event, rule: GroupRule | None, adapter: BaseAdapter | None = None
    ) -> str | None:  # noqa: ANN001
        """防刷屏：窗口内超频则临时禁言并返回拦截原因。"""
        if not rule or not rule.anti_flood_enabled or not event.is_group or not event.group_id:
            return None
        window = max(5, int(rule.flood_window_seconds or 60))
        limit = max(2, int(rule.flood_max_messages or 8))
        key = f"flood:{event.bot_id}:{event.group_id}:{event.user_id}"
        count = await self.cache.incr(key, ttl=window)
        if count <= limit:
            return None

        mute_seconds = int(rule.flood_mute_seconds or 0)
        if mute_seconds > 0 and adapter is not None:
            try:
                await adapter.mute_member(str(event.group_id), event.user_id, mute_seconds)
            except Exception:  # noqa: BLE001
                logger.warning("自动禁言失败：%s/%s", event.group_id, event.user_id)
        logger.warning(
            "群 %s 用户 %s 触发防刷屏（%s 次/%ss）",
            event.group_id, event.user_id, count, window,
        )
        return f"触发防刷屏（{count} 次/{window}s）"

    # ------------------------------------------------------------------
    # 固定关键词回复
    # ------------------------------------------------------------------
    def match_fixed_reply(self, rule: GroupRule | None, text: str) -> str | None:
        """固定关键词回复：命中则跳过 AI。配置在 rule.extra.fixed_replies。"""
        if not rule or not text:
            return None
        replies = (rule.extra or {}).get("fixed_replies") or []
        for item in replies:
            if not isinstance(item, dict):
                continue
            keyword = str(item.get("keyword") or "").strip()
            reply = str(item.get("reply") or "").strip()
            if not keyword or not reply:
                continue
            match_type = str(item.get("match") or "contains")
            if match_type == "exact" and text.strip() == keyword:
                return reply
            if match_type == "regex":
                import re

                try:
                    if re.search(keyword, text):
                        return reply
                except re.error:
                    logger.warning("固定回复正则无效：%s", keyword)
            elif keyword in text:
                return reply
        return None

    # ------------------------------------------------------------------
    # 入群 / 退群通知
    # ------------------------------------------------------------------
    async def handle_notice(
        self, event, adapter: BaseAdapter | None = None, rule: GroupRule | None = None
    ) -> str | None:  # noqa: ANN001
        """群通知：入群发欢迎语、退群发提示（占位符 {name} / {group}）。

        仅在单群规则显式开启且配置了文案时发送；规则缺失或开关关闭则静默。
        ``{name}`` 渲染为 @ 成员（无用户 ID 时回退纯文本"新朋友"）。
        """
        if not event.is_group or not event.group_id or rule is None or adapter is None:
            return None
        sub_type = str(event.sub_type or "")
        who = str(event.user_id or "")
        if sub_type == "group_increase":
            if not rule.welcome_enabled or not (rule.welcome_text or "").strip():
                return None
            template = rule.welcome_text
        elif sub_type == "group_decrease":
            if not (rule.leave_notice or "").strip():
                return None
            template = rule.leave_notice
        else:
            return None

        from backend.common.message import MessagePayload, MessageSegment

        rendered = template.replace("{group}", rule.group_name or str(event.group_id))
        payload = MessagePayload()
        if "{name}" in rendered:
            head, _, tail = rendered.partition("{name}")
            if head.strip():
                payload.add_text(head.strip())
            if who:
                payload.segments.append(
                    MessageSegment(type="at", data={"user_id": who})
                )
            if tail.strip():
                payload.add_text(tail.strip())
        else:
            payload.add_text(rendered)
        if payload.is_empty:
            payload = MessagePayload.from_text(who or "新朋友")
        try:
            result = await adapter.send_group(str(event.group_id), payload)
        except Exception as exc:  # noqa: BLE001 - 通知发送失败只记日志
            logger.warning("群通知发送失败：%s/%s %s", event.bot_id, event.group_id, exc)
            return None
        if not result.success:
            logger.warning("群通知发送失败：%s/%s %s", event.bot_id, event.group_id, result.error)
            return None
        logger.info(
            "群通知已发送：%s %s %s（群 %s）",
            event.bot_id, sub_type, who, event.group_id,
        )
        return payload.text or f"@{who}"

    # ------------------------------------------------------------------
    # 主动管理动作
    # ------------------------------------------------------------------
    async def mute(
        self, adapter: BaseAdapter, group_id: str, user_id: str, seconds: int = 60
    ) -> SendResult:
        return await adapter.mute_member(group_id, user_id, seconds)

    async def kick(
        self, adapter: BaseAdapter, group_id: str, user_id: str
    ) -> SendResult:
        return await adapter.kick_member(group_id, user_id)

    # ------------------------------------------------------------------
    def _clean_payload(self, data: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        allowed = {
            "bot_id", "group_id", "group_name",
            "enabled_ai", "enabled_emoji", "enabled_voice", "enabled_search",
            "enabled_push", "enabled_memory",
            "welcome_enabled", "welcome_text", "leave_notice",
            "block_words", "blacklist", "anti_flood_enabled",
            "flood_window_seconds", "flood_max_messages", "flood_mute_seconds",
            "character_id", "model_id", "extra",
        }
        payload = {key: value for key, value in data.items() if key in allowed}
        if creating and not payload.get("group_id"):
            raise ValidationError("群号不能为空")
        for field in ("block_words", "blacklist"):
            if field in payload and not isinstance(payload[field], list):
                raise ValidationError(f"{field} 必须是数组")
        return payload
