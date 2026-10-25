"""群组规则与群管理动作接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.dependencies import get_account_service, get_group_service, require_admin
from backend.routers.serializers import row_out
from backend.services.account_service import AccountService
from backend.services.group_admin_service import GroupAdminService

router = APIRouter(prefix="/api/groups", tags=["群组管理"])


class GroupRulePayload(BaseModel):
    bot_id: str | None = None
    group_id: str | None = None
    group_name: str | None = None
    enabled_ai: bool | None = None
    enabled_emoji: bool | None = None
    enabled_voice: bool | None = None
    enabled_search: bool | None = None
    enabled_push: bool | None = None
    enabled_memory: bool | None = None
    welcome_enabled: bool | None = None
    welcome_text: str | None = None
    leave_notice: str | None = None
    block_words: list[str] | None = None
    blacklist: list[str] | None = None
    anti_flood_enabled: bool | None = None
    flood_window_seconds: int | None = None
    flood_max_messages: int | None = None
    flood_mute_seconds: int | None = None
    character_id: str | None = None
    model_id: str | None = None
    extra: dict[str, Any] | None = None


class MuteRequest(BaseModel):
    bot_id: str
    group_id: str
    user_id: str
    seconds: int = 60


class KickRequest(BaseModel):
    bot_id: str
    group_id: str
    user_id: str


@router.get("", summary="群规则列表")
async def list_rules(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    bot_id: str | None = None,
    keyword: str | None = None,
    _=Depends(require_admin),
    service: GroupAdminService = Depends(get_group_service),
):
    items, total = await service.list_page(
        page, page_size, bot_id=bot_id, keyword=keyword
    )
    return {
        "items": [row_out(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/lookup", summary="按群号查询生效规则")
async def lookup_rule(
    bot_id: str = Query(...),
    group_id: str = Query(...),
    _=Depends(require_admin),
    service: GroupAdminService = Depends(get_group_service),
):
    rule = await service.get_rule(bot_id, group_id)
    return row_out(rule) if rule else None


@router.post("", summary="新建群规则")
async def create_rule(
    payload: GroupRulePayload,
    _=Depends(require_admin),
    service: GroupAdminService = Depends(get_group_service),
):
    return row_out(await service.create(payload.model_dump(exclude_none=True)))


@router.put("/{rule_id}", summary="更新群规则")
async def update_rule(
    rule_id: str,
    payload: GroupRulePayload,
    _=Depends(require_admin),
    service: GroupAdminService = Depends(get_group_service),
):
    return row_out(await service.update(rule_id, payload.model_dump(exclude_none=True)))


@router.delete("/{rule_id}", summary="删除群规则")
async def delete_rule(
    rule_id: str,
    _=Depends(require_admin),
    service: GroupAdminService = Depends(get_group_service),
):
    await service.delete(rule_id)
    return {"message": "已删除"}


@router.post("/actions/mute", summary="禁言群成员")
async def mute_member(
    payload: MuteRequest,
    _=Depends(require_admin),
    service: GroupAdminService = Depends(get_group_service),
    accounts: AccountService = Depends(get_account_service),
):
    adapter = accounts.build_adapter(await accounts.get_account(payload.bot_id))
    result = await service.mute(adapter, payload.group_id, payload.user_id, payload.seconds)
    return {"success": result.success, "error": result.error}


@router.post("/actions/kick", summary="移出群成员")
async def kick_member(
    payload: KickRequest,
    _=Depends(require_admin),
    service: GroupAdminService = Depends(get_group_service),
    accounts: AccountService = Depends(get_account_service),
):
    adapter = accounts.build_adapter(await accounts.get_account(payload.bot_id))
    result = await service.kick(adapter, payload.group_id, payload.user_id)
    return {"success": result.success, "error": result.error}
