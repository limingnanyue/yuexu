"""文字回复转换为通话桥 PCM，图片通过原账号私聊发送。"""

from __future__ import annotations

import asyncio
from contextlib import aclosing

from fastapi import WebSocket, WebSocketDisconnect

from backend.adapters.base_adapter import AdapterOptions, BaseAdapter, SendResult
from backend.adapters.napcat_adapter import NapCatAdapter
from backend.common.constants import MessageScene
from backend.common.exceptions import AdapterError, AppError
from backend.common.message import MessagePayload
from backend.services.tts_service import TTSService


class VoiceCallAdapter(NapCatAdapter):
    """使用既有分发器，仅将回复出口换为通话 PCM。"""

    def __init__(self, account_id: str, user_id: str, websocket: WebSocket, tts: TTSService,
                 *, message_adapter: BaseAdapter | None = None):
        super().__init__(AdapterOptions(account_id=account_id))
        self.user_id = user_id
        self.websocket = websocket
        self.tts = tts
        self.message_adapter = message_adapter

    async def send_message(self, scene: MessageScene, target_id: str, payload: MessagePayload) -> SendResult:
        if scene != MessageScene.PRIVATE or target_id != self.user_id:
            raise AdapterError("通话回复目标不匹配")
        images = [segment for segment in payload.segments if segment.type == "image"]
        if images:
            if self.message_adapter is None:
                return SendResult(success=False, error="通话图片发送通道未连接")
            result = await self.message_adapter.send_message(scene, target_id, MessagePayload.from_segments(images))
            if not result.success or not payload.text.strip():
                return result
        if not payload.text.strip():
            return SendResult(success=False, error="通话只支持文字合成语音")
        try:
            await self.websocket.send_json({"type": "speaking", "active": True})
            loop = asyncio.get_running_loop()
            deadline = loop.time()
            async with aclosing(self.tts.stream_pcm(payload.text)) as audio:
                async for chunk in audio:
                    for offset in range(0, len(chunk), 3200):
                        frame = chunk[offset:offset + 3200]
                        await asyncio.sleep(max(0, deadline - loop.time()))
                        await self.websocket.send_bytes(frame)
                        deadline = max(deadline, loop.time()) + len(frame) / 32000
            await asyncio.sleep(max(0, deadline - loop.time()))
            return SendResult(success=True)
        except AppError as exc:
            await self.websocket.send_json({"type": "error", "message": exc.message})
            return SendResult(success=False, error=exc.message)
        finally:
            try:
                await self.websocket.send_json({"type": "speaking", "active": False})
            except (WebSocketDisconnect, RuntimeError):
                pass
