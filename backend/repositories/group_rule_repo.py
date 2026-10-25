"""群组规则数据访问。"""

from __future__ import annotations

from backend.database.models import GroupRule
from backend.repositories.base import BaseRepository


class GroupRuleRepo(BaseRepository):
    model = GroupRule

    async def get_rule(self, bot_id: str, group_id: str) -> GroupRule | None:
        """优先取账号专属规则，其次取全局（bot_id 为空）规则。"""
        specific = await self.first(bot_id=bot_id, group_id=group_id)
        if specific:
            return specific
        return await self.first(bot_id=None, group_id=group_id)

    async def list_by_bot(self, bot_id: str) -> list[GroupRule]:
        return await self.all(bot_id=bot_id)

    async def delete_rule(self, rule_id: str) -> bool:
        rule = await self.get(rule_id)
        if not rule:
            return False
        await self.delete(rule)
        return True
