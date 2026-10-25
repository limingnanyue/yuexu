"""后台鉴权：登录、令牌签发、用户管理（文档第 7 章权限体系）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.constants import Role
from backend.common.crypto import (
    create_access_token,
    hash_password,
    verify_password,
)
from backend.common.exceptions import AuthError, ConflictError, NotFoundError, PermissionDeniedError
from backend.core.config_loader import get_config
from backend.database.models import AdminUser
from backend.repositories.user_repo import UserRepo


class AuthService:
    """后台账号服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = UserRepo(session)
        self.config = get_config()

    # ------------------------------------------------------------------
    async def login(self, username: str, password: str) -> tuple[AdminUser, str]:
        user = await self.repo.get_by_username(username)
        if not user or not verify_password(password, user.password_hash):
            raise AuthError("用户名或密码错误")
        if not user.is_active:
            raise PermissionDeniedError("该账号已被禁用")
        user.last_login_at = datetime.now()
        await self.session.flush()
        token = self.issue_token(user)
        return user, token

    def issue_token(self, user: AdminUser) -> str:
        return create_access_token(
            user.id,
            secret=self.config.get("security.jwt_secret", "change-me"),
            minutes=int(self.config.get("security.jwt_expire_minutes", 720)),
            algorithm=self.config.get("security.jwt_algorithm", "HS256"),
            role=user.role,
            extra={"username": user.username},
        )

    async def get_user(self, user_id: str) -> AdminUser:
        user = await self.repo.get(user_id)
        if not user:
            raise AuthError("账号不存在或已被删除")
        return user

    async def change_password(
        self, user: AdminUser, old_password: str, new_password: str
    ) -> None:
        if not verify_password(old_password, user.password_hash):
            raise AuthError("原密码不正确")
        if len(new_password) < 6:
            raise AuthError("新密码长度不能少于 6 位")
        user.password_hash = hash_password(new_password)
        await self.session.flush()

    # ------------------------------------------------------------------
    async def list_users(self) -> list[AdminUser]:
        return await self.repo.list(limit=200, order_by="created_at", desc=False)

    async def create_user(
        self, username: str, password: str, *, role: str = Role.ADMIN.value, nickname: str = ""
    ) -> AdminUser:
        if await self.repo.get_by_username(username):
            raise ConflictError(f"用户名已存在：{username}")
        if len(password) < 6:
            raise AuthError("密码长度不能少于 6 位")
        return await self.repo.create(
            username=username,
            password_hash=hash_password(password),
            role=role,
            nickname=nickname,
        )

    async def update_user(
        self,
        user_id: str,
        *,
        nickname: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        password: str | None = None,
    ) -> AdminUser:
        user = await self.get_user(user_id)
        values: dict[str, Any] = {}
        if nickname is not None:
            values["nickname"] = nickname
        if role is not None:
            values["role"] = role
        if is_active is not None:
            values["is_active"] = is_active
        if password:
            if len(password) < 6:
                raise AuthError("密码长度不能少于 6 位")
            values["password_hash"] = hash_password(password)
        return await self.repo.update(user, **values)

    async def delete_user(self, user_id: str, operator: AdminUser) -> None:
        if user_id == operator.id:
            raise ConflictError("不能删除当前登录账号")
        user = await self.repo.get(user_id)
        if not user:
            raise NotFoundError("账号不存在")
        if user.role == Role.OWNER and await self.repo.count(role=Role.OWNER.value) <= 1:
            raise ConflictError("至少保留一个超级主人账号")
        await self.repo.delete(user)

    # ------------------------------------------------------------------
    async def ensure_default_admin(self) -> AdminUser | None:
        """首次启动时按配置创建超管账号。"""
        if await self.repo.count() > 0:
            return None
        username = str(self.config.get("security.admin.username", "admin"))
        password = str(self.config.get("security.admin.password", "admin123"))
        nickname = str(self.config.get("security.admin.nickname", "管理员"))
        user = await self.repo.create(
            username=username,
            password_hash=hash_password(password),
            role=Role.OWNER.value,
            nickname=nickname,
        )
        return user
