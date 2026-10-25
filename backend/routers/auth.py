"""后台登录与用户管理接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.common.constants import Role
from backend.dependencies import (
    get_auth_service,
    get_client_ip,
    get_current_user,
    require_owner,
)
from backend.database.models import AdminUser
from backend.routers.serializers import row_out
from backend.services.auth_service import AuthService
from backend.services.log_service import LogService

router = APIRouter(prefix="/api/auth", tags=["后台鉴权"])


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    role: str = Role.ADMIN.value
    nickname: str = ""


class UserUpdateRequest(BaseModel):
    nickname: str | None = None
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


@router.post("/login", summary="后台登录")
async def login(
    payload: LoginRequest,
    service: AuthService = Depends(get_auth_service),
    ip: str = Depends(get_client_ip),
):
    user, token = await service.login(payload.username, payload.password)
    # 登录日志与本次登录共用同一请求会话
    await LogService(service.session).log_operation(
        "后台登录", module="auth", detail=user.username, user_id=user.id, ip=ip
    )
    return {"token": token, "user": row_out(user, exclude={"password_hash"})}


@router.get("/me", summary="当前登录账号")
async def me(user: AdminUser = Depends(get_current_user)):
    return row_out(user, exclude={"password_hash"})


@router.post("/change-password", summary="修改密码")
async def change_password(
    payload: ChangePasswordRequest,
    user: AdminUser = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    await service.change_password(user, payload.old_password, payload.new_password)
    return {"message": "密码修改成功"}


@router.get("/users", summary="后台账号列表")
async def list_users(
    _: AdminUser = Depends(require_owner),
    service: AuthService = Depends(get_auth_service),
):
    return [
        row_out(item, exclude={"password_hash"})
        for item in await service.list_users()
    ]


@router.post("/users", summary="新建后台账号")
async def create_user(
    payload: UserCreateRequest,
    _: AdminUser = Depends(require_owner),
    service: AuthService = Depends(get_auth_service),
):
    user = await service.create_user(
        payload.username, payload.password, role=payload.role, nickname=payload.nickname
    )
    return row_out(user, exclude={"password_hash"})


@router.put("/users/{user_id}", summary="更新后台账号")
async def update_user(
    user_id: str,
    payload: UserUpdateRequest,
    _: AdminUser = Depends(require_owner),
    service: AuthService = Depends(get_auth_service),
):
    user = await service.update_user(
        user_id,
        nickname=payload.nickname,
        role=payload.role,
        is_active=payload.is_active,
        password=payload.password,
    )
    return row_out(user, exclude={"password_hash"})


@router.delete("/users/{user_id}", summary="删除后台账号")
async def delete_user(
    user_id: str,
    operator: AdminUser = Depends(require_owner),
    service: AuthService = Depends(get_auth_service),
):
    await service.delete_user(user_id, operator)
    return {"message": "已删除"}
