"""Edge-TTS / OpenAI 兼容 / MiniMax 语音，缓存自动清理，失败降级为文字。"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import re
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

from backend.common.exceptions import TTSError
from backend.common.logger import get_logger
from backend.common.utils import clean_text, ensure_dir, truncate
from backend.core.config_loader import get_config

logger = get_logger("yuexu.service.tts")


class TTSService:
    """文本转语音与缓存管理。"""

    def __init__(self) -> None:
        self.config = get_config()
        self.last_error: str | None = None
        self.cache_dir = ensure_dir(
            self.config.resolve_path(str(self.config.get("tts.cache_dir", "static/voice_cache")))
        )

    # ------------------------------------------------------------------
    # 能力 / 开关
    # ------------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.config.get("tts.enabled", True))

    @property
    def available(self) -> bool:
        """当前引擎具备合成条件，云端引擎不依赖 edge-tts。"""
        engine = self.config.get("tts.engine", "edge")
        if engine in {"openai", "minimax"}:
            try:
                self.speech_url(str(self.config.get("tts.base_url", "https://api.openai.com/v1")), engine)
            except ValueError:
                return False
            return bool(
                str(self.config.get("tts.api_key", "") or "").strip()
                and str(self.config.get("tts.model", "") or "").strip()
                and str(self.config.get("tts.cloud_voice", "alloy") or "").strip()
            )
        return engine == "edge" and importlib.util.find_spec("edge_tts") is not None

    @staticmethod
    def speech_url(base_url: str, engine: str = "openai") -> str:
        """允许 API 根地址或完整 speech 地址，不接受 URL 内的凭据。"""
        try:
            url = httpx.URL(base_url.strip())
        except httpx.InvalidURL as exc:
            raise ValueError("语音 API 地址无效") from exc
        if (url.scheme not in {"http", "https"} or not url.host
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("语音 API 地址须为不含凭据、查询参数的 HTTP(S) 地址")
        address = str(url).rstrip("/")
        suffix = "/t2a_v2" if engine == "minimax" else "/audio/speech"
        if engine == "minimax" and url.path in {"", "/"}:
            address += "/v1"
        return address if address.endswith(suffix) else address + suffix

    def should_speak(
        self, event, group_rule=None, *, reply_text: str | None = None,
        history: list[dict] | None = None,
    ) -> bool:
        if not self.enabled:
            return False
        if group_rule is not None and getattr(group_rule, "enabled_voice", True) is False:
            return False
        trigger = str(self.config.get("tts.trigger", "auto"))
        if trigger == "never":
            return False
        if trigger == "always":
            return True
        if trigger == "auto":
            if reply_text is not None and (
                not reply_text.strip()
                or len(reply_text) > min(int(self.config.get("tts.max_chars", 200)), 1000)
                or re.search(r"`|https?://|www\.|(?m:^\s*(?:[-*+]\s|\d+[.)、]\s|\|))", reply_text)
            ):
                return False
            if event.is_group and not event.is_at_me:
                return False
            # shortcut: 使用近期用户表达的确定性线索，复杂反讽或隐含意图需要模型分类时再升级。
            preference = self._voice_preference(event.text)
            if preference is None:
                recent_users = [item for item in (history or []) if item.get("role") == "user"][-6:]
                for item in reversed(recent_users):
                    preference = self._voice_preference(str(item.get("content") or ""))
                    if preference is not None:
                        break
            if preference is not None:
                return preference
            if any(segment.type == "voice" for segment in event.segments):
                return True
            emotional_text = re.sub(
                r"(?:不|没)(?:要|想|是|再|有)?(?:难过|委屈|孤独|失眠|睡不着|安慰|陪|抱抱)", "", event.text,
            )
            return not event.is_group and bool(re.search(
                r"难过|委屈|想哭|崩溃|好累|抱抱|安慰|陪陪我|陪我聊|孤独|失眠|睡不着|哄我|想你", emotional_text,
            ))
        # at_only：群里仅 @ 时语音，私聊默认语音
        return event.is_group is False or bool(event.is_at_me)

    @staticmethod
    def _voice_preference(text: str) -> bool | None:
        text = re.sub(r"(?:不(?:要|用|想)|别)(?:用|发|回)?(?:文字|打字|文本)", "", text)
        if re.search(
            r"(?:不(?:要|用|想|愿意|能|方便|需要)|别|避免|没法|无法)[^，,。.!！?？;；\n]{0,6}(?:语音|声音|听|说话)"
            r"|语音[^，,。.!！?？;；\n]{0,3}(?:不要|不用|别)|不方便听|别出声|安静点|静音"
            r"|(?:我在|正在|现在在)(?:开会|上课)"
            r"|(?:打字|文字|文本)(?:就好|就行|吧|回复|说)|(?:用|发|回|改成|换成|切换到)(?:文字|文本)", text,
        ):
            return False
        if re.search(r"(?:怎么|如何|怎样).{0,8}(?:语音|声音)|(?:语音|声音).{0,8}(?:配置|设置|功能|接口|合成|模型|音色|报错|失败|问题)", text):
            return None
        if re.search(
            r"(?:发|回|用|来|换成|改成|切换到)(?:一(?:条|段|个))?语音"
            r"|(?:想|想要|要|好想|让我)听(?:一?听)?.{0,5}(?:你|声音|说话)"
            r"|(?:现在|已经).{0,3}(?:方便听|可以听|能听)|可以发语音", text,
        ):
            return True
        return None

    # ------------------------------------------------------------------
    # 合成
    # ------------------------------------------------------------------
    async def stream_pcm(self, text: str) -> AsyncIterator[bytes]:
        """MiniMax 通话语音流：16 kHz / 16 bit / 单声道，不写入文件缓存。"""
        if not self.enabled or self.config.get("tts.engine") != "minimax" or not self.available:
            raise TTSError("通话语音需要启用并完整配置 MiniMax TTS")
        try:
            content = clean_text(text, 10000)
            if not content:
                raise TTSError("通话语音文本为空")
            if len(content) >= 10000:
                raise TTSError("通话语音文本须少于 10000 字符")
            speed = float(self.config.get("tts.speed", 1))
            if not 0.5 <= speed <= 2:
                raise TTSError("MiniMax 语速范围为 0.5–2 倍")
            body = {
                "model": self.config.get("voice_call.tts_model") or self.config.get("tts.model"), "text": content,
                "stream": True, "output_format": "hex",
                "stream_options": {"exclude_aggregated_audio": True},
                "voice_setting": {"voice_id": self.config.get("tts.cloud_voice"), "speed": speed},
                "audio_setting": {"format": "pcm", "sample_rate": 16000, "channel": 1},
            }
            url = self.speech_url(str(self.config.get("tts.base_url", "")), "minimax")
            emitted = False
            async with httpx.AsyncClient(timeout=float(self.config.get("tts.timeout", 60))) as client:
                async with client.stream("POST", url, json=body, headers={
                    "Authorization": f"Bearer {self.config.get('tts.api_key')}",
                }) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        result = json.loads(line[5:].strip())
                        code = result["base_resp"]["status_code"]
                        if type(code) is not int or code != 0:
                            suffix = f"（错误码 {code}）" if type(code) is int else ""
                            raise TTSError(f"MiniMax 通话语音服务返回错误{suffix}")
                        data = result["data"]
                        status = data["status"]
                        if type(status) is not int or status not in {1, 2}:
                            raise TTSError("MiniMax 通话语音状态无效")
                        audio = bytes.fromhex(data.get("audio") or "")
                        if len(audio) % 2:
                            raise TTSError("MiniMax 返回的 PCM 音频不完整")
                        # 部分服务忽略 exclude_aggregated_audio，末块仍返回整段音频。
                        if audio and (status == 1 or not emitted):
                            emitted = True
                            yield audio
                        if status == 2:
                            if not emitted:
                                raise TTSError("MiniMax 返回的通话音频为空")
                            return
            raise TTSError("MiniMax 通话语音流提前结束")
        except httpx.HTTPStatusError as exc:
            raise TTSError(f"MiniMax 通话语音请求失败（HTTP {exc.response.status_code}）") from None
        except httpx.TimeoutException:
            raise TTSError("MiniMax 通话语音请求超时") from None
        except httpx.HTTPError:
            raise TTSError("MiniMax 通话语音连接失败") from None
        except (KeyError, TypeError, ValueError):
            raise TTSError("MiniMax 通话语音数据或配置无效") from None

    async def synthesize(self, text: str, voice: str | None = None) -> str | None:
        """文本转 mp3，返回本地文件路径；失败返回 None。"""
        self.last_error = None
        if not self.enabled or not self.available:
            return None
        temporary: Path | None = None
        try:
            limit = min(int(self.config.get("tts.max_chars", 200)), 1000)
            content = clean_text(text, max(len(text), 1))
            if not content:
                return None
            if len(content) > limit:
                raise TTSError(f"语音文本超过 {limit} 字，请缩短内容或发送完整文字")
            engine = self.config.get("tts.engine", "edge")
            cloud = engine in {"openai", "minimax"}
            voice_name = voice or str(self.config.get(
                "tts.cloud_voice" if cloud else "tts.voice",
                "alloy" if cloud else "zh-CN-XiaoxiaoNeural",
            ))
            rate = str(self.config.get("tts.rate", "+0%"))
            volume = str(self.config.get("tts.volume", "+0%"))
            url = self.speech_url(str(self.config.get("tts.base_url", "https://api.openai.com/v1")), engine) if cloud else ""
            model = str(self.config.get("tts.model", "") or "")
            api_key = str(self.config.get("tts.api_key", "") or "")
            speed = float(self.config.get("tts.speed", 1))
            cache_key = hashlib.sha256(json.dumps(
                [engine, url, model, api_key, content, voice_name, speed, rate, volume],
                ensure_ascii=False,
            ).encode("utf-8")).hexdigest()[:32]
            target = self.cache_dir / f"{cache_key}.mp3"
            if target.exists() and target.stat().st_size > 0:
                return str(target)

            # 独立临时文件避免并发读取或失败后复用半截语音。
            with tempfile.NamedTemporaryFile(dir=self.cache_dir, suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
            if cloud:
                timeout = float(self.config.get("tts.timeout", 60))
                if engine == "minimax":
                    if not 0.5 <= speed <= 2:
                        raise TTSError("MiniMax 语速范围为 0.5–2 倍")
                    body = {"model": model, "text": content, "stream": False, "output_format": "hex",
                            "voice_setting": {"voice_id": voice_name, "speed": speed},
                            "audio_setting": {"format": "mp3"}}
                else:
                    body = {"model": model, "input": content, "voice": voice_name,
                            "response_format": "mp3", "speed": speed}
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        url, headers={"Authorization": f"Bearer {api_key}"},
                        json=body,
                        timeout=timeout,
                    )
                response.raise_for_status()
                if engine == "minimax":
                    result = response.json()
                    status = result["base_resp"]["status_code"]
                    if status != 0:
                        if status == 1004:
                            raise TTSError("MiniMax 鉴权失败（1004），请检查 API Key 是否有效且与接口所属站点一致")
                        code = f"（错误码 {status}）" if type(status) is int else ""
                        raise TTSError(f"MiniMax 语音服务返回错误{code}")
                    if result["data"]["status"] != 2:
                        raise TTSError("MiniMax 语音合成未完成")
                    audio = bytes.fromhex(result["data"]["audio"])
                    content_type = "audio/mpeg"
                else:
                    audio = response.content
                    content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if (content_type not in {"", "audio/mpeg", "audio/mp3", "application/octet-stream"}
                        or not (audio.startswith(b"ID3") or (len(audio) >= 2 and audio[0] == 255 and audio[1] & 224 == 224))):
                    raise TTSError("云端服务未返回 MP3 音频")
                temporary.write_bytes(audio)
            else:
                import edge_tts

                communicate = edge_tts.Communicate(content, voice_name, rate=rate, volume=volume)
                await asyncio.wait_for(communicate.save(str(temporary)), timeout=45)
            if not temporary.exists() or temporary.stat().st_size == 0:
                raise TTSError("生成的语音文件为空")
            temporary.replace(target)
            logger.info("TTS 合成完成：%s（%s 字符）", target.name, len(content))
            return str(target)
        except Exception as exc:  # noqa: BLE001 - 语音失败不影响文字回复
            # 仅展示本地生成的提示，不回显可能携带密钥的上游错误正文。
            if isinstance(exc, TTSError):
                self.last_error = exc.message
            elif isinstance(exc, httpx.HTTPStatusError):
                status = exc.response.status_code
                if status in {401, 403}:
                    self.last_error = f"云端语音鉴权失败（HTTP {status}），请检查 API Key 与接口地址"
                else:
                    self.last_error = f"云端语音请求失败（HTTP {status}），请稍后重试"
            elif isinstance(exc, httpx.TimeoutException):
                self.last_error = "语音合成请求超时，请稍后重试或增加请求超时设置"
            logger.warning("TTS 合成失败，已降级为文字（%s）", self.last_error or type(exc).__name__)
            return None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    logger.debug("删除语音临时文件失败")

    # ------------------------------------------------------------------
    # 缓存运维
    # ------------------------------------------------------------------
    async def cleanup_cache(self, max_age_hours: int | None = None) -> int:
        hours = max_age_hours if max_age_hours is not None else int(
            self.config.get("tts.cache_ttl_hours", 24)
        )
        if hours <= 0:
            return 0
        deadline = time.time() - hours * 3600
        removed = 0
        for file in self.cache_dir.glob("*.mp3"):
            try:
                if file.stat().st_mtime < deadline:
                    file.unlink()
                    removed += 1
            except OSError:
                logger.debug("删除语音缓存失败：%s", file)
        if removed:
            logger.info("已清理过期语音缓存 %s 个", removed)
        return removed

    async def clear_cache(self) -> int:
        removed = 0
        for file in self.cache_dir.glob("*.mp3"):
            try:
                file.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def cache_stats(self) -> dict[str, int | str]:
        files = list(self.cache_dir.glob("*.mp3"))
        total_size = sum(file.stat().st_size for file in files if file.exists())
        return {
            "count": len(files),
            "size": total_size,
            "dir": str(self.cache_dir),
            "available": self.available,
            "enabled": self.enabled,
        }

    def list_voices(self) -> list[dict[str, str]]:
        """当前引擎的常用音色，兼容服务的自定义名称也可直接填写。"""
        if self.config.get("tts.engine", "edge") == "minimax":
            return [{"value": "Chinese (Mandarin)_Warm_Bestie", "label": "温暖闺蜜"}]
        if self.config.get("tts.engine", "edge") == "openai":
            return [{"value": name, "label": name} for name in (
                "alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx",
                "sage", "shimmer", "verse", "marin", "cedar",
            )]
        return [
            {"value": "zh-CN-XiaoxiaoNeural", "label": "晓晓（温柔女声）"},
            {"value": "zh-CN-XiaoyiNeural", "label": "晓伊（活泼女声）"},
            {"value": "zh-CN-YunxiNeural", "label": "云希（年轻男声）"},
            {"value": "zh-CN-YunjianNeural", "label": "云健（沉稳男声）"},
            {"value": "zh-CN-liaoning-XiaobeiNeural", "label": "晓北（东北女声）"},
            {"value": "zh-CN-shaanxi-XiaoniNeural", "label": "晓妮（陕西女声）"},
        ]

    @staticmethod
    def voice_path_exists(file_path: str) -> bool:
        return bool(file_path) and Path(file_path).exists()
