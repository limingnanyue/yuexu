"""自动消息推送任务接口（开发文档 4.11）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, StrictBool

from backend.dependencies import get_current_user, get_push_service, get_session, require_admin
from backend.common.exceptions import ValidationError
from backend.database.models import AdminUser
from backend.routers.serializers import row_out, task_out
from backend.repositories.log_repo import LogRepo
from backend.repositories.user_push_repo import UserPushRepo
from backend.services.proactive_push_service import ProactivePushService
from backend.services.auto_push_service import AutoPushService

router = APIRouter(prefix="/api/push-tasks", tags=["自动推送"])


class PushTaskPayload(BaseModel):
    name: str | None = None
    bot_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    target_name: str | None = None
    content: dict[str, Any] | None = None
    trigger_type: str | None = None
    delay_seconds: int | None = None
    cron_expr: str | None = None
    interval_seconds: int | None = None
    run_at: datetime | None = None
    enabled: bool | None = None
    paused: bool | None = None
    daily_limit: int | None = None
    retry_max: int | None = None


class ToggleRequest(BaseModel):
    enabled: bool = True


class PauseRequest(BaseModel):
    paused: bool = True


class UserPushSwitchPayload(BaseModel):
    user_push_switch: StrictBool


class ReadReceiptPayload(BaseModel):
    bot_id: str = Field(min_length=1, max_length=40)
    user_id: str = Field(min_length=1, max_length=64)
    message_id: str = Field(min_length=1, max_length=128)
    read_at: datetime | None = None


@router.get("/users", summary="私聊惦记用户与频次")
async def list_push_users(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None, _=Depends(require_admin), session=Depends(get_session),
):
    rows, total = await UserPushRepo(session).list_users(page, page_size, keyword)
    items = []
    for state, name, day_count, week_count in rows:
        data = row_out(state, exclude={"claim_token", "claim_until", "activity_version", "last_memory_key"})
        items.append(dict(data, account_name=name or state.bot_id,
                          day_push_count=day_count or 0, week_push_count=week_count or 0))
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/records", summary="惦记推送与反馈留存")
async def list_push_records(
    page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=200),
    bot_id: str | None = None, user_id: str | None = None,
    _=Depends(require_admin), session=Depends(get_session),
):
    records, total = await UserPushRepo(session).list_records(page, page_size, bot_id, user_id)
    return {"items": [row_out(item) for item in records], "total": total, "page": page, "page_size": page_size}


@router.put("/users/{bot_id}/{user_id}", summary="关闭用户主动消息")
async def stop_user_push(
    bot_id: str, user_id: str, payload: UserPushSwitchPayload,
    admin=Depends(require_admin), session=Depends(get_session),
):
    if payload.user_push_switch:
        raise ValidationError("只能由用户在私聊中重新开启主动消息")
    state = await UserPushRepo(session).disable_user(bot_id, user_id)
    await LogRepo(session).add_operation(
        module="push", action="管理员关闭主动消息", user_id=admin.id,
        detail=f"{bot_id}/{user_id}",
    )
    return row_out(state, exclude={"claim_token", "claim_until", "activity_version", "last_memory_key"})


@router.post("/feedback/read", summary="接入可信平台已读回执")
async def push_read_receipt(
    payload: ReadReceiptPayload, _=Depends(require_admin), session=Depends(get_session),
):
    # 没有真实回执的平台不调用此入口，未读保持 pending。
    read_at = payload.read_at
    if read_at is not None and read_at.tzinfo is not None:
        read_at = read_at.astimezone().replace(tzinfo=None)
    accepted = await ProactivePushService(session).mark_read(
        payload.bot_id, payload.user_id, payload.message_id, at=read_at,
    )
    return {"accepted": accepted}


@router.get("", summary="推送任务列表")
async def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    bot_id: str | None = None,
    enabled: bool | None = None,
    keyword: str | None = None,
    _=Depends(require_admin),
    service: AutoPushService = Depends(get_push_service),
):
    items, total = await service.list_page(
        page, page_size, bot_id=bot_id, enabled=enabled, keyword=keyword
    )
    return {
        "items": [task_out(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", summary="新建推送任务")
async def create_task(
    payload: PushTaskPayload,
    user: AdminUser = Depends(require_admin),
    service: AutoPushService = Depends(get_push_service),
):
    data = payload.model_dump(exclude_none=True)
    if isinstance(data.get("run_at"), datetime):
        data["run_at"] = data["run_at"].isoformat()
    task = await service.create_task(data, created_by=user.id)
    return task_out(task)


@router.get("/{task_id}", summary="推送任务详情")
async def get_task(
    task_id: str,
    _=Depends(require_admin),
    service: AutoPushService = Depends(get_push_service),
):
    return task_out(await service.get_task(task_id))


@router.put("/{task_id}", summary="更新推送任务")
async def update_task(
    task_id: str,
    payload: PushTaskPayload,
    _=Depends(require_admin),
    service: AutoPushService = Depends(get_push_service),
):
    data = payload.model_dump(exclude_none=True)
    if isinstance(data.get("run_at"), datetime):
        data["run_at"] = data["run_at"].isoformat()
    task = await service.update_task(task_id, data)
    return task_out(task)


@router.delete("/{task_id}", summary="删除推送任务")
async def delete_task(
    task_id: str,
    _=Depends(require_admin),
    service: AutoPushService = Depends(get_push_service),
):
    await service.delete_task(task_id)
    return {"message": "已删除"}


@router.post("/{task_id}/enable", summary="启用 / 停用任务")
async def toggle_task(
    task_id: str,
    payload: ToggleRequest,
    _=Depends(require_admin),
    service: AutoPushService = Depends(get_push_service),
):
    return task_out(await service.set_enabled(task_id, payload.enabled))


@router.post("/{task_id}/pause", summary="暂停 / 恢复任务")
async def pause_task(
    task_id: str,
    payload: PauseRequest,
    _=Depends(require_admin),
    service: AutoPushService = Depends(get_push_service),
):
    return task_out(await service.set_paused(task_id, payload.paused))


@router.post("/{task_id}/run-now", summary="立即执行一次")
async def run_task_now(
    task_id: str,
    _=Depends(get_current_user),
    service: AutoPushService = Depends(get_push_service),
):
    task = await service.get_task(task_id)
    success = await service.execute_task(task)
    return {"success": success, "error": task.last_error, "next_run_at": task.next_run_at}
