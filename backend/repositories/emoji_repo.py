"""表情包数据访问。"""

from __future__ import annotations

from sqlalchemy import or_, select

from backend.database.models import EmojiItem
from backend.repositories.base import BaseRepository


class EmojiRepo(BaseRepository):
    model = EmojiItem

    async def get_by_key(self, key: str) -> EmojiItem | None:
        return await self.first(key=key)

    async def find_by_key_or_alias(self, key: str) -> EmojiItem | None:
        stmt = (
            select(EmojiItem)
            .where(or_(EmojiItem.key == key, EmojiItem.alias == key), EmojiItem.enabled.is_(True))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_enabled(self, category: str | None = None) -> list[EmojiItem]:
        conditions = [EmojiItem.enabled.is_(True)]
        if category:
            conditions.append(EmojiItem.category == category)
        stmt = select(EmojiItem).where(*conditions).order_by(EmojiItem.created_at.desc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
