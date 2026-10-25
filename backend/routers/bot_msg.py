"""消息接入：OneBot HTTP / WebSocket、QQ 官方签名回调与发送测试。"""

from __future__ import annotations

from typing import Any
import hmac
import secrets

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from backend.common.exceptions import AuthError, NotFoundError, ValidationError
from backend.common.constants import Platform
from backend.common.logger import get_logger
from backend.database.db import session_scope
from backend.dependencies import get_account_service, get_emoji_service, require_admin
from backend.repositories.account_repo import AccountRepo
from backend.services.account_service import AccountService
from backend.services.bot_dispatch_service import BotDispatchService
from backend.services.emoji_service import EmojiService
from backend.services.channel_service import dispatch_channel_payload
from backend.core.runtime import get_runtime

router = APIRouter(prefix="/api/bot", tags=["消息接入"])
logger = get_logger("yuexu.router.bot")


class SendRequest(BaseModel):
    account_id: str
    target_type: str = "group"
    target_id: str
    content: dict[str, Any]


@router.post("/managed/{account_id}", summary="受管 QQ 事件上报")
async def managed_webhook(account_id: str, request: Request, background: BackgroundTasks,
                          accounts: AccountService = Depends(get_account_service)):
    account = await accounts.get_account(account_id)
    token = account.adapter_token or ""
    adapter_config = account.adapter_config or {}
    if (account.platform != Platform.QQ.value
            or not (adapter_config.get("managed") is True or adapter_config.get("runtime") == "qq_av")
            or not token):
        raise AuthError("消息接入凭证无效")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 1024 * 1024:
            raise ValidationError("事件内容过大")
    signature = "sha1=" + hmac.digest(token.encode(), body, "sha1").hex()
    if not (secrets.compare_digest(request.headers.get("Authorization", "").encode(), f"Bearer {token}".encode())
            or secrets.compare_digest(request.headers.get("X-Signature", "").encode(), signature.encode())):
        raise AuthError("消息接入凭证无效")
    import json
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValidationError("事件内容必须为 JSON 对象") from exc
    if not isinstance(payload, dict):
        raise ValidationError("事件内容必须为 JSON 对象")
    if get_runtime().state_manager.is_online(account_id):
        background.add_task(dispatch_channel_payload, accounts.build_adapter(account), payload)
    return {"accepted": True}


@router.post("/qq/{account_id}", summary="QQ 官方机器人事件回调")
async def qq_webhook(account_id: str, request: Request, background: BackgroundTasks,
                     accounts: AccountService = Depends(get_account_service)):
    account = await accounts.get_account(account_id)
    if account.platform != Platform.QQ_BOT.value:
        raise ValidationError("该接入不是 QQ 官方机器人")
    adapter = accounts.build_adapter(account)
    body = await request.body()
    if len(body) > 1024 * 1024:
        raise ValidationError("事件内容过大")
    payload, response = adapter.parse_webhook(body, request.headers)
    if payload is not None and get_runtime().state_manager.is_online(account_id):
        background.add_task(dispatch_channel_payload, adapter, payload)
    return response


async def _dispatch_payload(account_id: str, payload: dict[str, Any], session) -> dict[str, Any]:
    account = await AccountRepo(session).get(account_id)
    if account is None:
        raise NotFoundError("机器人账号不存在")
    adapter = AccountService(session).build_adapter(account)
    event = adapter.parse_event(payload, account_id)
    if event is None:
        return {"accepted": False, "reason": "ignored"}
    await BotDispatchService(session, adapter=adapter).handle_event(event)
    return {"accepted": True, "post_type": event.post_type}


@router.post("/onebot/{account_id}", summary="OneBot11 HTTP 事件上报")
async def onebot_webhook(
    account_id: str,
    payload: dict[str, Any] = Body(...),
    _=Depends(require_admin),
):
    """NapCat / Gewechat 可通过 HTTP 上报事件到本接口。"""
    async with session_scope() as session:
        return await _dispatch_payload(account_id, payload, session)


@router.websocket("/onebot/ws/{account_id}")
async def onebot_websocket(websocket: WebSocket, account_id: str) -> None:
    """OneBot11 正向 WebSocket（NapCat 推荐方式）。

    NapCat 配置：WebSocket 客户端 -> ws://127.0.0.1:8000/api/bot/onebot/ws/{account_id}
    """
    await websocket.accept()
    try:
        async with session_scope() as session:
            account = await AccountRepo(session).get(account_id)
            if account is None:
                await websocket.send_json({"status": "error", "message": "账号不存在"})
                await websocket.close(code=4004)
                return
        await websocket.send_json({"status": "connected", "account_id": account_id})
        logger.info("OneBot WebSocket 已连接：%s", account_id)

        while True:
            payload = await websocket.receive_json()
            async with session_scope() as session:
                await _dispatch_payload(account_id, payload, session)
    except WebSocketDisconnect:
        logger.info("OneBot WebSocket 已断开：%s", account_id)
    except Exception:  # noqa: BLE001
        logger.exception("OneBot WebSocket 异常：%s", account_id)
        try:
            await websocket.close(code=1011)
        except Exception:  # noqa: BLE001
            pass


@router.post("/send", summary="测试发送消息")
async def send_message(
    payload: SendRequest,
    _=Depends(require_admin),
    accounts: AccountService = Depends(get_account_service),
    emojis: EmojiService = Depends(get_emoji_service),
):
    raise ValidationError("控制台不主动发送测试消息，请在私聊中向机器人发消息测试")
