"""Repository 基类：只做数据库读写，禁止包含业务规则。

约定：``filters`` 中值为 ``None`` 的键表示「不过滤」（如需查询 IS NULL 请
使用各 Repo 的专用方法），避免误把 None 当作条件。
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import Base

logger = logging.getLogger("yuexu.repository")


class BaseRepository:
    """通用 CRUD 封装，子类声明 ``model`` 即可。"""

    model: type[Base]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    def _columns(self, filters: dict[str, Any]):
        stmt = select(self.model)
        return self._apply_filters(stmt, filters)

    def _apply_filters(self, stmt, filters: dict[str, Any]):
        for key, value in filters.items():
            if value is None:
                continue
            column = getattr(self.model, key, None)
            if column is None:
                raise AttributeError(f"{self.model.__name__} 不存在字段 {key}")
            stmt = stmt.where(column == value)
        return stmt

    def _pk_columns(self) -> list[Any]:
        """主键列（UserPushState 等复合主键模型也适用）。"""
        return list(self.model.__mapper__.primary_key)

    def _order_clause(self, order_by: str, desc: bool):
        """排序字段不存在时回退主键排序，保证分页稳定不重不漏。"""
        column = getattr(self.model, order_by, None)
        if column is not None:
            return [column.desc() if desc else column.asc()]
        logger.debug(
            "%s 无排序字段 %s，回退主键排序（分页仍稳定）", self.model.__name__, order_by
        )
        return [item.desc() if desc else item.asc() for item in self._pk_columns()]

    # ------------------------------------------------------------------
    async def get(self, obj_id: str) -> Any | None:
        return await self.session.get(self.model, obj_id)

    async def get_many(self, ids: Sequence[str]) -> list[Any]:
        if not ids:
            return []
        stmt = select(self.model).where(self.model.id.in_(list(ids)))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def all(self, **filters: Any) -> list[Any]:
        stmt = self._apply_filters(select(self.model), filters)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def first(self, **filters: Any) -> Any | None:
        # 无显式排序时按主键排序，保证结果确定
        stmt = self._apply_filters(select(self.model), filters).order_by(
            *self._pk_columns()
        ).limit(1)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def exists(self, **filters: Any) -> bool:
        stmt = self._apply_filters(select(self.model.id), filters).limit(1)
        return (await self.session.execute(stmt)).first() is not None

    async def list(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        order_by: str = "created_at",
        desc: bool = True,
        **filters: Any,
    ) -> list[Any]:
        stmt = self._apply_filters(select(self.model), filters)
        stmt = stmt.order_by(*self._order_clause(order_by, desc))
        stmt = stmt.limit(max(1, limit)).offset(max(0, offset))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self, **filters: Any) -> int:
        stmt = self._apply_filters(select(func.count()).select_from(self.model), filters)
        return int(await self.session.scalar(stmt) or 0)

    async def paginate(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        order_by: str = "created_at",
        desc: bool = True,
        **filters: Any,
    ) -> tuple[list[Any], int]:
        total = await self.count(**filters)
        items = await self.list(
            limit=page_size,
            offset=(max(page, 1) - 1) * page_size,
            order_by=order_by,
            desc=desc,
            **filters,
        )
        return items, total

    # ------------------------------------------------------------------
    async def create(self, **values: Any) -> Any:
        obj = self.model(**values)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update(self, obj: Any, **values: Any) -> Any:
        for key, value in values.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
        await self.session.flush()
        return obj

    async def delete(self, obj: Any) -> None:
        await self.session.delete(obj)
        await self.session.flush()

    async def delete_by(self, **filters: Any) -> int:
        stmt = sa_delete(self.model)
        for key, value in filters.items():
            if value is None:
                continue
            stmt = stmt.where(getattr(self.model, key) == value)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)
