"""独立记忆库目录，不移动或复制记忆内容。"""

from sqlalchemy import func, select

from backend.database.migrate import backfill_memory_libraries
from backend.database.models import BotAccount, MemoryEntry, MemoryLibrary
from backend.repositories.base import BaseRepository


class MemoryLibraryRepo(BaseRepository):
    model = MemoryLibrary

    async def ensure_legacy(self) -> None:
        await backfill_memory_libraries(self.session)

    async def catalog(self) -> list[dict]:
        await self.ensure_legacy()
        memories = select(
            MemoryEntry.bot_id.label("library_id"), func.count().label("total"),
        ).group_by(MemoryEntry.bot_id).subquery()
        library_id = func.coalesce(func.nullif(BotAccount.memory_library_id, ""), BotAccount.id)
        accounts = select(
            library_id.label("library_id"), func.count().label("total"),
        ).group_by(library_id).subquery()
        result = await self.session.execute(
            select(MemoryLibrary, func.coalesce(memories.c.total, 0), func.coalesce(accounts.c.total, 0))
            .outerjoin(memories, memories.c.library_id == MemoryLibrary.id)
            .outerjoin(accounts, accounts.c.library_id == MemoryLibrary.id)
            .order_by(MemoryLibrary.created_at, MemoryLibrary.id)
        )
        return [{"id": library.id, "name": library.name, "platform": library.platform,
                 "memory_count": memory_count, "account_count": account_count}
                for library, memory_count, account_count in result]
