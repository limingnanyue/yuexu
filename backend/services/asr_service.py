"""本地 SenseVoice HTTP 识别：16 kHz 单声道 PCM 在内存中封装为 WAV。"""

from __future__ import annotations

import io
import math
import re
import wave

import httpx

from backend.common.exceptions import ExternalServiceError
from backend.common.logger import get_logger
from backend.core.config_loader import get_config

logger = get_logger("yuexu.service.asr")


class ASRError(ExternalServiceError):
    code = "ASR_ERROR"
    message = "语音识别失败"


class ASRService:
    def __init__(self) -> None:
        self.config = get_config()

    async def transcribe(self, pcm: bytes) -> str:
        """识别一段不超过 30 秒的 s16le PCM，取消操作交给通话层处理。"""
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > 16000 * 2 * 30:
            raise ASRError("识别音频须为不超过 30 秒的 16 位 PCM")
        address = str(self.config.get("voice_call.asr_url", "http://127.0.0.1:50000/api/v1/asr")).strip()
        try:
            url = httpx.URL(address)
            if (url.scheme not in {"http", "https"} or not url.host or url.username or url.password
                    or url.query or url.fragment or any(ord(char) < 33 for char in address)):
                raise ValueError
            timeout = float(self.config.get("voice_call.asr_timeout", 15))
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError
        except (httpx.InvalidURL, ValueError, TypeError) as exc:
            raise ASRError("语音识别地址或超时配置无效") from exc

        audio = io.BytesIO()
        with wave.open(audio, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(pcm)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                response = await client.post(
                    address,
                    files={"files": ("call.wav", audio.getvalue(), "audio/wav")},
                    data={"keys": "call", "lang": "auto", "use_itn": "true"},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("语音识别服务请求失败（%s）", type(exc).__name__)
            raise ASRError("语音识别服务不可用，请检查本地服务及超时配置") from exc
        try:
            result = response.json()["result"]
            if not isinstance(result, list):
                raise ValueError
            if not result:
                return ""
            text = result[0].get("clean_text")
            if text is None:
                text = result[0]["text"]
            if not isinstance(text, str):
                raise ValueError
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ASRError("语音识别服务返回的数据无效") from exc
        return re.sub(r"<\|[^<>]*\|>", "", text).strip()
