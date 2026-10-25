"""上下文会话管理接口（开发文档 4.6 / 第 6 章第 5 项）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.common.exceptions import NotFoundError
from backend.dependencies import get_context_service, require_admin, require_owner
from backend.services.context_service import ContextService

router = APIRouter(prefix="/api/contexts", tags=["上下文会话"])


class SessionKeyRequest(BaseModel):
    session_key: str


@router.get("", summary="会话列表")
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    _=Depends(require_admin),
    service: ContextService = Depends(get_context_service),
):
    items, total = await service.list_sessions(keyword=keyword, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/detail", summary="查看会话快照")
async def session_detail(
    session_key: str = Query(...),
    _=Depends(require_admin),
    service: ContextService = Depends(get_context_service),
):
    session = await service.get_snapshot(session_key)
    if session is None:
        raise NotFoundError("会话不存在或已过期")
    return session


@router.post("/clear", summary="清空会话上下文")
async def clear_session(
    payload: SessionKeyRequest,
    _=Depends(require_admin),
    service: ContextService = Depends(get_context_service),
):
    existed = await service.clear(payload.session_key)
    return {"message": "已清空" if existed else "会话不存在", "cleared": existed}


@router.post("/freeze", summary="冻结会话")
async def freeze_session(
    payload: SessionKeyRequest,
    _=Depends(require_admin),
    service: ContextService = Depends(get_context_service),
):
    if not await service.freeze(payload.session_key):
        raise NotFoundError("会话不存在或已过期")
    return {"message": "已冻结"}


@router.post("/unfreeze", summary="解冻会话")
async def unfreeze_session(
    payload: SessionKeyRequest,
    _=Depends(require_admin),
    service: ContextService = Depends(get_context_service),
):
    if not await service.unfreeze(payload.session_key):
        raise NotFoundError("会话不存在或已过期")
    return {"message": "已解冻"}


@router.post("/cleanup", summary="清理过期 / 无效会话")
async def cleanup_sessions(
    _=Depends(require_admin),
    service: ContextService = Depends(get_context_service),
):
    removed = await service.cleanup_expired()
    return {"message": "清理完成", "removed": removed}


@router.delete("", summary="清空全部会话（危险操作）")
async def clear_all_sessions(
    _=Depends(require_owner),
    service: ContextService = Depends(get_context_service),
):
    removed = await service.clear_all()
    return {"message": "已清空全部会话", "removed": removed}
