"""LLM 模型配置数据访问。"""

from __future__ import annotations

from sqlalchemy import update

from backend.database.models import LlmModel
from backend.repositories.base import BaseRepository


class ModelRepo(BaseRepository):
    model = LlmModel

    async def get_default(self) -> LlmModel | None:
        return await self.first(is_default=True, enabled=True)

    async def list_enabled(self) -> list[LlmModel]:
        return await self.list(limit=500, enabled=True, order_by="created_at", desc=True)

    async def clear_default(self, except_id: str | None = None) -> None:
        stmt = update(LlmModel).values(is_default=False).where(LlmModel.is_default.is_(True))
        if except_id:
            stmt = stmt.where(LlmModel.id != except_id)
        await self.session.execute(stmt)
        await self.session.flush()
