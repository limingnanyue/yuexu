"""长期记忆数据访问：数据库层负责持久化，向量索引由 vector_store 负责。

记忆隔离口径（4.5.1）：
- 私聊：target_type=user, target_id=用户 ID, group_id=NULL
- 群聊：target_type=user, target_id=用户 ID, group_id=群 ID（不跨群复用）
- 群级事实预留：target_type=group, target_id=群 ID
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Sequence

from sqlalchemy import and_, delete as sa_delete, func, or_, select, update

from backend.database.models import MemoryEntry
from backend.repositories.base import BaseRepository


class MemoryRepo(BaseRepository):
    model = MemoryEntry

    # ------------------------------------------------------------------
    # 后台管理查询
    # ------------------------------------------------------------------
    async def list_for_user(
        self,
        bot_id: str,
        user_id: str | None = None,
        *,
        scope_type: str | None = None,
        group_id: str | None = None,
        target_type: str | None = None,
        keyword: str | None = None,
        memory_type: str | None = None,
        rejected: bool | None = None,
        limit: int | None = 50,
        offset: int = 0,
    ) -> tuple[list[MemoryEntry], int]:
        conditions = [MemoryEntry.bot_id == bot_id]
        if user_id:
            conditions.append(MemoryEntry.user_id == user_id)
        if scope_type:
            conditions.append(MemoryEntry.scope_type == scope_type)
        if group_id:
            conditions.append(MemoryEntry.group_id == group_id)
        if target_type:
            conditions.append(MemoryEntry.target_type == target_type)
        if memory_type:
            conditions.append(MemoryEntry.memory_type == memory_type)
        if rejected is not None:
            conditions.append(MemoryEntry.rejected.is_(rejected))
        if keyword:
            pattern = f"%{keyword}%"
            conditions.append(
                or_(
                    MemoryEntry.content.like(pattern),
                    MemoryEntry.category.like(pattern),
                    MemoryEntry.memory_type.like(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(MemoryEntry).where(*conditions)
        total = int(await self.session.scalar(count_stmt) or 0)

        stmt = (
            select(MemoryEntry)
            .where(*conditions)
            .order_by(
                MemoryEntry.rejected.asc(),
                MemoryEntry.hot_score.desc(),
                MemoryEntry.created_at.desc(),
            )
            .offset(max(0, offset))
        )
        if limit is not None:
            stmt = stmt.limit(max(1, limit))
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    # ------------------------------------------------------------------
    # 检索候选
    # ------------------------------------------------------------------
    @staticmethod
    def _scope_conditions(
        bot_id: str,
        *,
        target_type: str,
        target_id: str,
        user_id: str | None = None,
        group_id: str | None = None,
        scope_type: str | None = None,
    ) -> list[Any]:
        conditions: list[Any] = [
            MemoryEntry.bot_id == bot_id,
            MemoryEntry.target_type == target_type,
            MemoryEntry.target_id == target_id,
        ]
        if user_id:
            conditions.append(MemoryEntry.user_id == user_id)
        if scope_type == "private":
            conditions.append(MemoryEntry.group_id.is_(None))
        elif scope_type == "group":
            conditions.append(MemoryEntry.group_id == group_id)
        elif group_id:
            conditions.append(MemoryEntry.group_id == group_id)
        return conditions

    async def list_for_retrieval(
        self,
        bot_id: str,
        *,
        target_type: str = "user",
        target_id: str,
        user_id: str | None = None,
        group_id: str | None = None,
        scope_type: str | None = None,
        limit: int = 200,
        exclude_rejected: bool = True,
        created_after: datetime | None = None,
    ) -> list[MemoryEntry]:
        conditions = self._scope_conditions(
            bot_id,
            target_type=target_type,
            target_id=target_id,
            user_id=user_id,
            group_id=group_id,
            scope_type=scope_type,
        )
        if exclude_rejected:
            conditions.append(MemoryEntry.rejected.is_(False))
        if created_after is not None:
            conditions.append(MemoryEntry.created_at >= created_after)
        stmt = (
            select(MemoryEntry)
            .where(*conditions)
            .order_by(MemoryEntry.hot_score.desc(), MemoryEntry.created_at.desc())
            .limit(max(1, limit))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_group_memories(
        self,
        bot_id: str,
        group_id: str,
        *,
        limit: int = 8,
        exclude_rejected: bool = True,
    ) -> list[MemoryEntry]:
        """按群维度取记忆（不区分具体用户）：群聊活力 Agent 取素材用。"""
        conditions: list[Any] = [
            MemoryEntry.bot_id == bot_id,
            MemoryEntry.group_id == group_id,
        ]
        if exclude_rejected:
            conditions.append(MemoryEntry.rejected.is_(False))
        stmt = (
            select(MemoryEntry)
            .where(*conditions)
            .order_by(MemoryEntry.hot_score.desc(), MemoryEntry.created_at.desc())
            .limit(max(1, limit))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search_candidates(
        self,
        bot_id: str,
        keywords: Sequence[str],
        *,
        target_type: str = "user",
        target_id: str,
        user_id: str | None = None,
        group_id: str | None = None,
        scope_type: str | None = None,
        limit: int = 50,
        exclude_rejected: bool = True,
        created_after: datetime | None = None,
    ) -> list[MemoryEntry]:
        """关键词兜底召回（向量不可用 / 模糊模式双路召回）。"""
        conditions = self._scope_conditions(
            bot_id,
            target_type=target_type,
            target_id=target_id,
            user_id=user_id,
            group_id=group_id,
            scope_type=scope_type,
        )
        if exclude_rejected:
            conditions.append(MemoryEntry.rejected.is_(False))
        if created_after is not None:
            conditions.append(MemoryEntry.created_at >= created_after)
        if keywords:
            patterns = [f"%{keyword}%" for keyword in keywords]
            conditions.append(or_(*(MemoryEntry.content.like(pattern) for pattern in patterns)))
        stmt = (
            select(MemoryEntry)
            .where(*conditions)
            .order_by(MemoryEntry.hot_score.desc(), MemoryEntry.created_at.desc())
            .limit(max(1, limit))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_exact(
        self,
        bot_id: str,
        *,
        target_type: str,
        target_id: str,
        user_id: str,
        group_id: str | None,
        content: str,
    ) -> MemoryEntry | None:
        conditions = [
            MemoryEntry.bot_id == bot_id,
            MemoryEntry.target_type == target_type,
            MemoryEntry.target_id == target_id,
            MemoryEntry.user_id == user_id,
            MemoryEntry.content == content,
        ]
        if group_id:
            conditions.append(MemoryEntry.group_id == group_id)
        else:
            conditions.append(MemoryEntry.group_id.is_(None))
        stmt = select(MemoryEntry).where(*conditions).limit(1)
        return (await self.session.execute(stmt)).scalars().first()

    async def recent_for_target(
        self,
        bot_id: str,
        *,
        target_type: str,
        target_id: str,
        user_id: str,
        group_id: str | None = None,
        limit: int = 50,
    ) -> list[MemoryEntry]:
        return await self.list_for_retrieval(
            bot_id,
            target_type=target_type,
            target_id=target_id,
            user_id=user_id,
            group_id=group_id,
            scope_type="group" if group_id else "private",
            limit=limit,
        )

    async def identity_candidates(
        self,
        bot_id: str,
        *,
        target_type: str,
        target_id: str,
        user_id: str,
        group_id: str | None = None,
        limit: int = 200,
    ) -> list[MemoryEntry]:
        """身份属性候选（姓名 / 住址 / 年龄 / 生日），供新值覆盖旧值。

        旧实现只看最近 60 条；用户聊了几十轮日常后再搬家，旧住址可能已经
        被挤出窗口，导致新旧地址同时可召回。这里先用 SQL 圈出“可能含身份
        属性”的条目（数量远小于全部记忆），再交给 ``identity_fact`` 精确
        解析；索引仍可走 target 复合索引，写入路径开销可控。
        """
        conditions = self._scope_conditions(
            bot_id,
            target_type=target_type,
            target_id=target_id,
            user_id=user_id,
            group_id=group_id,
            scope_type="group" if group_id else "private",
        )
        conditions.append(MemoryEntry.rejected.is_(False))
        patterns = (
            "%我叫%", "%我的名字%", "%名字是%", "%住在%", "%家在%",
            "%来自%", "%岁%", "%生日%",
        )
        conditions.append(or_(*(MemoryEntry.content.like(pattern) for pattern in patterns)))
        stmt = (
            select(MemoryEntry)
            .where(*conditions)
            .order_by(MemoryEntry.created_at.desc())
            .limit(max(1, limit))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # 批量更新 / 维护
    # ------------------------------------------------------------------
    async def update_entries(self, ids: Iterable[str], **values: Any) -> int:
        id_list = [item for item in ids if item]
        if not id_list:
            return 0
        stmt = (
            update(MemoryEntry)
            .where(MemoryEntry.id.in_(id_list))
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)

    async def decay_hot(self, factor: float) -> int:
        if factor <= 0 or factor >= 1:
            return 0
        stmt = (
            update(MemoryEntry)
            .where(MemoryEntry.hot_score > 0)
            .values(hot_score=MemoryEntry.hot_score * factor)
            # evaluate：已加载对象的 hot_score 同步改成新值。用 False 时旧值会留在
            # 会话里，下一次 flush 覆盖回数据库，热度衰减就静默失效了。
            .execution_options(synchronize_session="evaluate")
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)

    async def purge_cold(
        self,
        *,
        before: datetime,
        hot_below: float,
        limit: int = 500,
    ) -> list[str]:
        """找出长期未使用且热度极低的冷记忆。"""
        stmt = (
            select(MemoryEntry.id)
            .where(
                MemoryEntry.hot_score < hot_below,
                MemoryEntry.rejected.is_(False),
                or_(
                    and_(MemoryEntry.last_hit_at.is_not(None), MemoryEntry.last_hit_at < before),
                    and_(MemoryEntry.last_hit_at.is_(None), MemoryEntry.created_at < before),
                ),
            )
            .limit(max(1, limit))
        )
        result = await self.session.execute(stmt)
        return [str(item) for item in result.scalars().all()]

    async def delete_ids(self, ids: Sequence[str]) -> int:
        if not ids:
            return 0
        stmt = sa_delete(MemoryEntry).where(MemoryEntry.id.in_(list(ids)))
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)

    async def ids_where(self, *conditions: Any) -> list[str]:
        """按条件取 id 列表（重置 / 重建等批量操作避免载入全量实体）。"""
        stmt = select(MemoryEntry.id).where(*conditions)
        result = await self.session.execute(stmt)
        return [str(item) for item in result.scalars().all()]

    async def iter_entries(
        self, batch: int = 100, *, bot_id: str | None = None
    ):
        """按 (created_at, id) 游标分批遍历记忆，支持全量维护任务不载入全表。"""
        batch = max(1, int(batch))
        last_created: datetime | None = None
        last_id = ""
        while True:
            conditions: list[Any] = []
            if bot_id:
                conditions.append(MemoryEntry.bot_id == bot_id)
            if last_created is not None:
                conditions.append(
                    or_(
                        MemoryEntry.created_at > last_created,
                        and_(
                            MemoryEntry.created_at == last_created,
                            MemoryEntry.id > last_id,
                        ),
                    )
                )
            stmt = (
                select(MemoryEntry)
                .where(*conditions)
                .order_by(MemoryEntry.created_at.asc(), MemoryEntry.id.asc())
                .limit(batch)
            )
            rows = list((await self.session.execute(stmt)).scalars().all())
            if not rows:
                return
            yield rows
            if len(rows) < batch:
                return
            last_created = rows[-1].created_at
            last_id = rows[-1].id

    async def count_all(self, bot_id: str | None = None) -> int:
        if bot_id:
            return await self.count(bot_id=bot_id)
        return await self.count()

    async def delete_by_scope(
        self, bot_id: str, *, scope_type: str | None = None, group_id: str | None = None
    ) -> int:
        conditions: dict = {"bot_id": bot_id}
        if scope_type:
            conditions["scope_type"] = scope_type
        if group_id:
            conditions["group_id"] = group_id
        return await self.delete_by(**conditions)

    async def group_counts(self, bot_id: str | None = None) -> dict[str, Any]:
        """按类型 / 否定状态统计，仪表盘与记忆页共用。"""
        stmt = select(MemoryEntry.memory_type, func.count()).group_by(MemoryEntry.memory_type)
        if bot_id:
            stmt = stmt.where(MemoryEntry.bot_id == bot_id)
        by_type = {str(key): int(value) for key, value in (await self.session.execute(stmt)).all()}

        rejected_stmt = select(func.count()).select_from(MemoryEntry).where(
            MemoryEntry.rejected.is_(True)
        )
        if bot_id:
            rejected_stmt = rejected_stmt.where(MemoryEntry.bot_id == bot_id)
        rejected = int(await self.session.scalar(rejected_stmt) or 0)
        return {"by_type": by_type, "rejected": rejected}
