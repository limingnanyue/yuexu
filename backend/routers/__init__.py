"""API 路由聚合：所有路由挂载在 ``/api`` 下。"""

from fastapi import APIRouter

from backend.routers.account import router as account_router
from backend.routers.auth import router as auth_router
from backend.routers.auto_push import router as push_router
from backend.routers.bot_msg import router as bot_router
from backend.routers.character import router as character_router
from backend.routers.context import router as context_router
from backend.routers.emotion import router as emotion_router
from backend.routers.emoji import router as emoji_router
from backend.routers.group_rule import router as group_router
from backend.routers.image import router as image_router
from backend.routers.llm_model import router as model_router
from backend.routers.log import router as log_router
from backend.routers.memory import router as memory_router
from backend.routers.search import router as search_router
from backend.routers.system import router as system_router
from backend.routers.tts import router as tts_router
from backend.routers.vitality import router as vitality_router
from backend.routers.voice_call import router as voice_call_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(system_router)
api_router.include_router(account_router)
api_router.include_router(character_router)
api_router.include_router(memory_router)
api_router.include_router(context_router)
api_router.include_router(model_router)
api_router.include_router(group_router)
api_router.include_router(push_router)
api_router.include_router(emoji_router)
api_router.include_router(tts_router)
api_router.include_router(image_router)
api_router.include_router(search_router)
api_router.include_router(log_router)
api_router.include_router(bot_router)
api_router.include_router(emotion_router)
api_router.include_router(vitality_router)
api_router.include_router(voice_call_router)

__all__ = ["api_router"]
