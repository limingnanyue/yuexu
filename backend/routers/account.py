"""机器人账号接口（扫码登录、状态、配置绑定）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.dependencies import get_account_service, require_admin
from backend.services.account_service import AccountService

router = APIRouter(prefix="/api/accounts", tags=["机器人账号"])


class AccountPayload(BaseModel):
    name: str | None = None
    platform: str | None = None
    account_no: str | None = None
    adapter_base_url: str | None = None
    adapter_token: str | None = None
    adapter_config: dict[str, Any] | None = None
    character_id: str | None = None
    model_id: str | None = None
    memory_library_id: str | None = Field(default=None, max_length=40, strict=True)
    settings: dict[str, Any] | None = None
    auto_connect: bool | None = None


class LoginCodePayload(BaseModel):
    verify_code: str


@router.get("", summary="账号列表")
async def list_accounts(
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    return await service.list_accounts()


@router.post("", summary="新增机器人账号")
async def create_account(
    payload: AccountPayload,
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    account = await service.create_account(payload.model_dump(exclude_none=True))
    return await service.get_detail(account.id)


@router.get("/memory-libraries", summary="可绑定的记忆库（包含已删除连接保留的记忆）")
async def list_memory_libraries(
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    return await service.list_memory_libraries()


@router.get("/{account_id}", summary="账号详情")
async def get_account(
    account_id: str,
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    return await service.get_detail(account_id)


@router.put("/{account_id}", summary="更新账号配置")
async def update_account(
    account_id: str,
    payload: AccountPayload,
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    await service.update_account(account_id, payload.model_dump(exclude_none=True))
    return await service.get_detail(account_id)


@router.delete("/{account_id}", summary="删除账号")
async def delete_account(
    account_id: str,
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    await service.delete_account(account_id)
    return {"message": "已删除"}


@router.post("/{account_id}/qrcode", summary="获取登录二维码")
async def request_qrcode(
    account_id: str,
    refresh: bool = False,
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    return await service.request_qrcode(account_id, refresh=refresh)


@router.post("/{account_id}/prepare", summary="自动准备扫码登录环境")
async def prepare_login(account_id: str, _=Depends(require_admin),
                        service: AccountService = Depends(get_account_service)):
    return await service.prepare_login(account_id, start=True)


@router.get("/{account_id}/prepare", summary="查询扫码准备进度")
async def preparation_status(account_id: str, _=Depends(require_admin),
                             service: AccountService = Depends(get_account_service)):
    return await service.prepare_login(account_id)


@router.post("/{account_id}/login-code", summary="提交微信 ClawBot 登录验证码")
async def submit_login_code(account_id: str, payload: LoginCodePayload,
                            _=Depends(require_admin), service: AccountService = Depends(get_account_service)):
    return await service.poll_login(account_id, verify_code=payload.verify_code)


@router.get("/{account_id}/login-status", summary="轮询扫码状态")
async def poll_login(
    account_id: str,
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    return await service.poll_login(account_id)


@router.post("/{account_id}/logout", summary="手动下线")
async def logout(
    account_id: str,
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    return await service.logout(account_id)


@router.post("/{account_id}/reconnect", summary="重新连接")
async def reconnect(
    account_id: str,
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    return await service.reconnect(account_id)


@router.get("/{account_id}/groups", summary="拉取群列表")
async def get_groups(
    account_id: str,
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    return await service.get_groups(account_id)


@router.get("/{account_id}/friends", summary="拉取好友列表")
async def get_friends(
    account_id: str,
    _=Depends(require_admin),
    service: AccountService = Depends(get_account_service),
):
    return await service.get_friends(account_id)
