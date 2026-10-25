"""全局依赖注入：数据库会话、登录鉴权、权限校验、Service 工厂。

路由层统一通过 ``Depends`` 获取 Service，不直接操作数据库。
"""

from __future__ import annotations

from typing import AsyncIterator, Callable

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.common.constants import Role
from backend.common.crypto import decode_access_token
from backend.common.exceptions import AuthError, PermissionDeniedError
from backend.core.config_loader import get_config
from backend.core.runtime import RuntimeContext, get_runtime
from backend.core.state_manager import AccountStateManager
from backend.database.db import get_session_factory
from backend.database.models import AdminUser
from backend.services.account_service import AccountService
from backend.services.auth_service import AuthService
from backend.services.auto_push_service import AutoPushService
from backend.services.bot_dispatch_service import BotDispatchService
from backend.services.character_service import CharacterService
from backend.services.context_service import ContextService
from backend.services.emoji_service import EmojiService
from backend.services.emotion_service import EmotionService
from backend.services.group_admin_service import GroupAdminService
from backend.services.image_service import ImageService
from backend.services.llm_service import LLMService
from backend.services.log_service import LogService
from backend.services.memory_service import MemoryService
from backend.services.search_service import SearchService
from backend.services.system_service import SystemService
from backend.services.tts_service import TTSService
from backend.services.vitality_service import VitalityService

bearer_scheme = HTTPBearer(auto_error=False, description="后台登录令牌")


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------
async def get_session() -> AsyncIterator:
    """请求级数据库会话，成功后自动提交。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_runtime_ctx() -> RuntimeContext:
    return get_runtime()


def get_state_manager() -> AccountStateManager:
    return get_runtime().state_manager


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.client.host if request.client else ""


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session=Depends(get_session),
) -> AdminUser:
    if credentials is None or not credentials.credentials:
        raise AuthError("请先登录后台")
    config = get_config()
    payload = decode_access_token(
        credentials.credentials,
        secret=str(config.get("security.jwt_secret", "change-me")),
        algorithm=str(config.get("security.jwt_algorithm", "HS256")),
    )
    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("登录凭证无效")
    user = await AuthService(session).get_user(str(user_id))
    if not user.is_active:
        raise PermissionDeniedError("账号已被禁用")
    return user


def require_roles(*roles: str) -> Callable:
    """权限依赖：主人拥有全部权限，管理员按配置放行。"""

    allowed = set(roles)

    async def dependency(user: AdminUser = Depends(get_current_user)) -> AdminUser:
        if user.role == Role.OWNER.value:
            return user
        if user.role not in allowed:
            raise PermissionDeniedError("当前账号没有该操作权限")
        return user

    return dependency


require_admin = require_roles(Role.ADMIN.value)
require_owner = require_roles(Role.OWNER.value)


# ---------------------------------------------------------------------------
# Service 工厂
# ---------------------------------------------------------------------------
def get_auth_service(session=Depends(get_session)) -> AuthService:
    return AuthService(session)


def get_account_service(
    session=Depends(get_session),
    state: AccountStateManager = Depends(get_state_manager),
) -> AccountService:
    return AccountService(session, state_manager=state)


def get_character_service(session=Depends(get_session)) -> CharacterService:
    return CharacterService(session)


def get_context_service() -> ContextService:
    return ContextService()


def get_memory_service(session=Depends(get_session)) -> MemoryService:
    return MemoryService(session)


def get_emotion_service(session=Depends(get_session)) -> EmotionService:
    return EmotionService(session)


def get_llm_service(session=Depends(get_session)) -> LLMService:
    return LLMService(session)


def get_search_service(session=Depends(get_session)) -> SearchService:
    return SearchService(session)


def get_group_service(session=Depends(get_session)) -> GroupAdminService:
    return GroupAdminService(session)


def get_push_service(session=Depends(get_session)) -> AutoPushService:
    return AutoPushService(session)


def get_emoji_service(session=Depends(get_session)) -> EmojiService:
    return EmojiService(session)


def get_tts_service() -> TTSService:
    return TTSService()


def get_image_service() -> ImageService:
    return ImageService()


def get_log_service(session=Depends(get_session)) -> LogService:
    return LogService(session)


def get_system_service(session=Depends(get_session)) -> SystemService:
    return SystemService(session)


def get_vitality_service(session=Depends(get_session)) -> VitalityService:
    return VitalityService(session)


def get_dispatch_service(session=Depends(get_session)) -> BotDispatchService:
    return BotDispatchService(session)
