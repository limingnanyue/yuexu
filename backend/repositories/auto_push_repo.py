"""自动推送任务数据访问。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select

from backend.database.models import AutoPushTask
from backend.repositories.base import BaseRepository


class AutoPushRepo(BaseRepository):
    model = AutoPushTask

    async def list_enabled(self) -> list[AutoPushTask]:
        return await self.all(enabled=True)

    async def list_by_bot(self, bot_id: str) -> list[AutoPushTask]:
        return await self.all(bot_id=bot_id)

    async def list_due(self, moment: datetime, limit: int = 50) -> list[AutoPushTask]:
        """取出到点需要执行的任务。"""
        stmt = (
            select(AutoPushTask)
            .where(
                AutoPushTask.enabled.is_(True),
                AutoPushTask.paused.is_(False),
                AutoPushTask.next_run_at.is_not(None),
                AutoPushTask.next_run_at <= moment,
            )
            .order_by(AutoPushTask.next_run_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_page(
        self,
        page: int,
        page_size: int,
        *,
        bot_id: str | None = None,
        enabled: bool | None = None,
        keyword: str | None = None,
    ) -> tuple[list[AutoPushTask], int]:
        conditions = []
        if bot_id:
            conditions.append(AutoPushTask.bot_id == bot_id)
        if enabled is not None:
            conditions.append(AutoPushTask.enabled.is_(enabled))
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(
                or_(AutoPushTask.name.like(pattern), AutoPushTask.target_name.like(pattern))
            )

        from sqlalchemy import func

        count_stmt = select(func.count()).select_from(AutoPushTask)
        if conditions:
            count_stmt = count_stmt.where(*conditions)
        total = int(await self.session.scalar(count_stmt) or 0)

        stmt = select(AutoPushTask)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = (
            stmt.order_by(AutoPushTask.created_at.desc())
            .limit(max(1, page_size))
            .offset((max(page, 1) - 1) * page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total
