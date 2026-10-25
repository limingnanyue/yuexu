"""人设数据访问。"""

from __future__ import annotations

from sqlalchemy import update

from backend.database.models import Character
from backend.repositories.base import BaseRepository


class CharacterRepo(BaseRepository):
    model = Character

    async def get_default(self) -> Character | None:
        return await self.first(is_default=True, enabled=True)

    async def list_enabled(self) -> list[Character]:
        return await self.list(limit=1000, enabled=True, order_by="created_at", desc=True)

    async def clear_default(self, except_id: str | None = None) -> None:
        stmt = update(Character).values(is_default=False).where(Character.is_default.is_(True))
        if except_id:
            stmt = stmt.where(Character.id != except_id)
        await self.session.execute(stmt)
        await self.session.flush()

    async def name_exists(self, name: str, exclude_id: str | None = None) -> bool:
        character = await self.first(name=name)
        return bool(character and character.id != exclude_id)
