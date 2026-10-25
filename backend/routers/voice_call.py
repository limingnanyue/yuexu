"""外部通话桥的月叙音频入口；本协议不属于 NapCat OneBot。"""

from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, WebSocket
from pydantic import ValidationError

from backend.common.constants import Platform
from backend.common.logger import get_logger
from backend.core.config_loader import get_config
from backend.database.db import session_scope
from backend.repositories.account_repo import AccountRepo
from backend.services.tts_service import TTSService
from backend.services.voice_call_service import VoiceCallSession, VoiceCallSettings

router = APIRouter(prefix="/api/voice-call", tags=["实时语音通话"])
logger = get_logger("yuexu.router.voice_call")
_active_calls: set[str] = set()


@router.websocket("/ws/{account_id}/{user_id}")
async def voice_call_websocket(websocket: WebSocket, account_id: str, user_id: str) -> None:
    try:
        settings = VoiceCallSettings.model_validate(get_config().section("voice_call"))
    except ValidationError:
        await websocket.close(code=1011, reason="通话配置无效")
        return
    if not settings.enabled or not re.fullmatch(r"[1-9][0-9]{4,19}", user_id):
        await websocket.close(code=1008)
        return

    async with session_scope() as session:
        account = await AccountRepo(session).get(account_id)
        token = account.adapter_token if account else ""
        authorized = bool(
            account and account.platform == Platform.QQ.value and token
            and secrets.compare_digest(
                websocket.headers.get("Authorization", "").encode(), f"Bearer {token}".encode(),
            )
        )
        self_id = str(account.account_no or "") if account else ""
    if not authorized or account_id in _active_calls:
        await websocket.close(code=1008)
        return
    tts = TTSService()
    if not tts.enabled or tts.config.get("tts.engine") != "minimax" or not tts.available:
        await websocket.close(code=1011, reason="请配置 MiniMax 语音引擎")
        return

    _active_calls.add(account_id)
    try:
        await websocket.accept()
        logger.info("通话音频连接：account=%s", account_id)
        await VoiceCallSession(websocket, account_id=account_id, user_id=user_id,
                               self_id=self_id, settings=settings).run()
    finally:
        _active_calls.discard(account_id)
        logger.info("通话音频断开：account=%s", account_id)
