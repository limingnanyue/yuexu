"""后台用户数据访问。"""

from __future__ import annotations

from backend.database.models import AdminUser
from backend.repositories.base import BaseRepository


class UserRepo(BaseRepository):
    model = AdminUser

    async def get_by_username(self, username: str) -> AdminUser | None:
        return await self.first(username=username)

    async def count(self, **filters) -> int:  # type: ignore[override]
        return await super().count(**filters)

    async def create_user(
        self, username: str, password_hash: str, *, role: str = "admin", nickname: str = ""
    ) -> AdminUser:
        return await self.create(
            username=username,
            password_hash=password_hash,
            role=role,
            nickname=nickname,
        )
