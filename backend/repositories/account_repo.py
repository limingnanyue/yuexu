"""机器人账号数据访问。"""

from __future__ import annotations

from backend.database.models import BotAccount
from backend.repositories.base import BaseRepository


class AccountRepo(BaseRepository):
    model = BotAccount

    async def list_all(self) -> list[BotAccount]:
        return await self.all()

    async def get_by_platform_account(
        self, platform: str, account_no: str
    ) -> BotAccount | None:
        return await self.first(platform=platform, account_no=account_no)

    async def list_by_platform(self, platform: str) -> list[BotAccount]:
        return await self.all(platform=platform)
