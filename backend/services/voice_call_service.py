"""月叙通话音频接入：16 kHz / s16le / mono，断句后复用消息分发。"""

from __future__ import annotations

import asyncio
import json
import math
import struct
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from backend.adapters.voice_call_adapter import VoiceCallAdapter
from backend.common.logger import get_logger
from backend.common.message import BotEvent, MessageSegment, SenderInfo
from backend.database.db import session_scope
from backend.services.account_service import AccountService
from backend.services.bot_dispatch_service import BotDispatchService
from backend.services.tts_service import TTSService

logger = get_logger("yuexu.voice_call")


class VoiceCallSettings(BaseModel):
    enabled: bool = False
    asr_url: str = "http://127.0.0.1:50000/api/v1/asr"
    asr_timeout: float = Field(default=15, ge=1, le=120)
    silence_ms: int = Field(default=600, ge=100, le=2000)
    min_speech_ms: int = Field(default=200, ge=60, le=1000)
    max_utterance_ms: int = Field(default=15000, ge=1000, le=30000)
    energy_threshold: int = Field(default=500, ge=1, le=32767)
    max_call_seconds: int = Field(default=600, ge=10, le=3600)


class PCMUtteranceBuffer:
    """固定 20ms 窗口的能量断句；无语音时不保留音频。"""

    def __init__(self, *, silence_ms=600, min_speech_ms=200,
                 max_utterance_ms=15000, energy_threshold=500):
        self.silence_frames = math.ceil(silence_ms / 20)
        self.min_speech_frames = math.ceil(min_speech_ms / 20)
        self.max_frames = math.ceil(max_utterance_ms / 20)
        self.threshold = energy_threshold
        self.pre_roll_bytes = min(3200, max(0, self.max_frames - self.min_speech_frames) * 640)
        self.pre_roll = bytearray()
        self.pending = bytearray()
        self.audio = bytearray()
        self.voiced = 0
        self.silent = 0
        self.max_energy = 0.0

    def feed(self, pcm: bytes) -> list[bytes]:
        self.pending.extend(pcm)
        result = []
        while len(self.pending) >= 640:
            frame = bytes(self.pending[:640])
            del self.pending[:640]
            energy = sum(sample[0] ** 2 for sample in struct.iter_unpack("<h", frame)) / 320
            self.max_energy = max(self.max_energy, energy)
            if energy >= self.threshold ** 2:
                if not self.audio:
                    self.audio.extend(self.pre_roll)
                    self.pre_roll.clear()
                self.voiced += 1
                self.silent = 0
            elif self.audio:
                self.silent += 1
            else:
                self.pre_roll.extend(frame)
                del self.pre_roll[:max(0, len(self.pre_roll) - self.pre_roll_bytes)]
                continue
            self.audio.extend(frame)
            if self.silent >= self.silence_frames or len(self.audio) >= self.max_frames * 640:
                audio = self._take_utterance()
                if audio:
                    result.append(audio)
        return result

    def _take_utterance(self) -> bytes:
        audio = bytes(self.audio) if self.voiced >= self.min_speech_frames else b""
        self.audio.clear()
        self.pre_roll.clear()
        self.voiced = self.silent = 0
        return audio

    def finish(self) -> bytes:
        if len(self.pending) % 2:
            raise ValueError("PCM 音频样本不完整")
        if self.audio:
            self.audio.extend(self.pending)
        self.pending.clear()
        return self._take_utterance()

    def reset(self) -> None:
        self.pending.clear()
        self._take_utterance()


class VoiceCallSession:
    def __init__(self, websocket: WebSocket, *, account_id: str, user_id: str,
                 self_id: str, settings: VoiceCallSettings):
        self.websocket = websocket
        self.account_id = account_id
        self.user_id = user_id
        self.self_id = self_id
        self.settings = settings
        self.call_id = uuid4().hex
        self.buffer = PCMUtteranceBuffer(**settings.model_dump(include={
            "silence_ms", "min_speech_ms", "max_utterance_ms", "energy_threshold",
        }))
        self.turn: asyncio.Task | None = None
        self.received_bytes = 0
        self.turns_started = 0

    async def _respond(self, pcm: bytes) -> None:
        from backend.services.asr_service import ASRService

        try:
            async with asyncio.timeout(180):
                started = asyncio.get_running_loop().time()
                text = await ASRService().transcribe(pcm)
                logger.info("通话识别完成：call=%s audio_ms=%d asr_ms=%d empty=%s", self.call_id,
                            len(pcm) // 32, (asyncio.get_running_loop().time() - started) * 1000, not text.strip())
                if not text.strip():
                    return
                await self.websocket.send_json({"type": "transcript", "text": text})
                event = BotEvent(
                    bot_id=self.account_id, user_id=self.user_id, self_id=self.self_id,
                    call_id=self.call_id, segments=[MessageSegment.text(text)], raw_message=text,
                    sender=SenderInfo(user_id=self.user_id),
                )
                async with session_scope() as session:
                    accounts = AccountService(session)
                    account = await accounts.get_account(self.account_id)
                    adapter = VoiceCallAdapter(
                        self.account_id, self.user_id, self.websocket, TTSService(),
                        message_adapter=accounts.build_adapter(account),
                    )
                    await BotDispatchService(session, adapter=adapter).handle_event(event)
        except WebSocketDisconnect:
            return
        except Exception as exc:
            logger.warning("通话处理失败：account=%s type=%s", self.account_id, type(exc).__name__)
            try:
                await self.websocket.send_json({"type": "error", "message": "通话处理失败，请检查 ASR、聊天模型和 MiniMax 设置"})
            except (WebSocketDisconnect, RuntimeError):
                pass
        finally:
            self.buffer.reset()
            try:
                await self.websocket.send_json({"type": "listening"})
            except (WebSocketDisconnect, RuntimeError):
                pass

    def _start_turn(self, pcm: bytes) -> None:
        if pcm and (self.turn is None or self.turn.done()):
            self.turns_started += 1
            self.turn = asyncio.create_task(self._respond(pcm), name=f"yuexu-call-{self.call_id}")

    async def run(self) -> None:
        close_code = None
        reason = ""
        try:
            await self.websocket.send_json({"type": "ready", "protocol": "yuexu-call-v1",
                                            "call_id": self.call_id, "sample_rate": 16000,
                                            "channels": 1, "encoding": "pcm_s16le"})
            async with asyncio.timeout(self.settings.max_call_seconds):
                while True:
                    message = await self.websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        return
                    pcm = message.get("bytes")
                    if pcm is not None:
                        if len(pcm) > 64000:
                            close_code = 1009
                            break
                        self.received_bytes += len(pcm)
                        # shortcut: 首版采用轮流说话，回复期间丢弃上行；接入回声消除后再支持打断。
                        if self.turn is not None and not self.turn.done():
                            continue
                        for utterance in self.buffer.feed(pcm):
                            self._start_turn(utterance)
                    else:
                        raw = message.get("text", "")
                        if len(raw) > 1024:
                            close_code = 1009
                            break
                        try:
                            control = json.loads(raw)
                        except ValueError:
                            control = None
                        if control == {"type": "end"}:
                            close_code = 1000
                            break
                        if control == {"type": "utterance_end"}:
                            try:
                                self._start_turn(self.buffer.finish())
                            except ValueError:
                                close_code = 1003
                                break
                        else:
                            close_code = 1003
                            break
        except TimeoutError:
            close_code = 1000
            reason = "通话达到时长上限"
        except WebSocketDisconnect:
            pass
        finally:
            logger.info("通话音频统计：call=%s pcm_bytes=%d peak_rms=%.1f turns=%d", self.call_id,
                        self.received_bytes, math.sqrt(self.buffer.max_energy), self.turns_started)
            if self.turn is not None:
                self.turn.cancel()
                await asyncio.gather(self.turn, return_exceptions=True)
            if close_code is not None:
                await self.websocket.close(code=close_code, reason=reason)
