"""Pydantic 基础模型：分页、统一输出结构。"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from backend.common.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

T = TypeVar("T")


class ORMModel(BaseModel):
    """可由 ORM 对象直接构造的模型基类。"""

    model_config = ConfigDict(from_attributes=True)


class PageQuery(BaseModel):
    """分页查询参数。"""

    page: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="每页条数"
    )
    keyword: str | None = Field(default=None, description="关键词，可选")

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


class PageResult(BaseModel, Generic[T]):
    """分页返回结构。"""

    items: list[T]
    total: int
    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE

    @classmethod
    def build(
        cls, items: list[T], total: int, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE
    ) -> "PageResult[T]":
        return cls(items=items, total=total, page=page, page_size=page_size)


class MsgOut(BaseModel):
    """简单操作结果。"""

    message: str = "ok"
    success: bool = True


class IdOut(BaseModel):
    """创建类接口返回。"""

    id: str


class CountOut(BaseModel):
    count: int = 0
