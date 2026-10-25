"""TTS 语音设置接口。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from pydantic import ValidationError as PydanticValidationError

from backend.common.exceptions import ValidationError
from backend.common.utils import mask_secret
from backend.dependencies import get_system_service, get_tts_service, require_admin
from backend.services.system_service import SystemService
from backend.services.tts_service import TTSService

router = APIRouter(prefix="/api/tts", tags=["TTS 语音"])


class TtsSettingsRequest(BaseModel):
    enabled: bool | None = None
    engine: Literal["edge", "openai", "minimax"] | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None
    cloud_voice: str | None = None
    speed: float | None = Field(default=None, ge=0.25, le=4)
    timeout: float | None = Field(default=None, ge=1, le=300)
    voice: str | None = None
    rate: str | None = Field(default=None, pattern=r"^[+-]\d+%$")
    volume: str | None = Field(default=None, pattern=r"^[+-]\d+%$")
    trigger: Literal["auto", "never", "at_only", "always"] | None = None
    max_chars: int | None = Field(default=None, ge=1, le=1000)
    cache_ttl_hours: int | None = Field(default=None, ge=0, le=720)

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is not None:
            TTSService.speech_url(value)
            return value.strip()
        return value

    @field_validator("model", "cloud_voice", "api_key", "voice")
    @classmethod
    def trim_value(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else value


class SynthesizeRequest(BaseModel):
    text: str
    voice: str | None = None


@router.get("/settings", summary="读取语音配置")
async def get_settings(
    _=Depends(require_admin),
    service: TTSService = Depends(get_tts_service),
):
    config = service.config
    return {
        "enabled": config.get("tts.enabled", True),
        "engine": config.get("tts.engine", "edge"),
        "base_url": config.get("tts.base_url", "https://api.openai.com/v1"),
        "api_key": mask_secret(config.get("tts.api_key", "")),
        "model": config.get("tts.model", ""),
        "cloud_voice": config.get("tts.cloud_voice", "alloy"),
        "speed": config.get("tts.speed", 1),
        "timeout": config.get("tts.timeout", 60),
        "voice": config.get("tts.voice", "zh-CN-XiaoxiaoNeural"),
        "rate": config.get("tts.rate", "+0%"),
        "volume": config.get("tts.volume", "+0%"),
        "trigger": config.get("tts.trigger", "auto"),
        "max_chars": config.get("tts.max_chars", 200),
        "cache_ttl_hours": config.get("tts.cache_ttl_hours", 24),
        "available": service.available,
    }


@router.put("/settings", summary="更新语音配置")
async def update_settings(
    payload: TtsSettingsRequest,
    _=Depends(require_admin),
    system: SystemService = Depends(get_system_service),
):
    patch = system._strip_masks(
        {"tts": payload.model_dump(exclude_none=True)}, system.config.data,
    ).get("tts", {})
    current = system.config.section("tts")
    merged = {**current, **patch}
    try:
        TtsSettingsRequest.model_validate(merged)
    except PydanticValidationError as exc:
        raise ValidationError("语音配置无效，请检查参数范围和 API 地址") from exc
    engine = merged.get("engine", "edge")
    if engine in {"openai", "minimax"}:
        if not str(merged.get("model", "") or "").strip():
            raise ValidationError("请填写云端语音模型名称")
        if not str(merged.get("cloud_voice", "alloy") or "").strip():
            raise ValidationError("请填写云端语音音色")
        if engine == "minimax" and not 0.5 <= float(merged.get("speed", 1)) <= 2:
            raise ValidationError("MiniMax 语速范围为 0.5–2 倍")
    if "base_url" in patch or engine != current.get("engine", "edge"):
        try:
            same_endpoint = TTSService.speech_url(
                str(merged.get("base_url", "https://api.openai.com/v1")), engine,
            ) == TTSService.speech_url(
                str(current.get("base_url", "https://api.openai.com/v1")), current.get("engine", "edge"),
            )
        except ValueError:
            same_endpoint = False
        if not same_endpoint and ("api_key" not in patch or patch["api_key"] == mask_secret(current.get("api_key", ""))):
            patch["api_key"] = ""
    saved = system.update_config({"tts": patch})
    settings = saved.get("tts", {})
    settings["api_key"] = mask_secret(system.config.get("tts.api_key", ""))
    return {"message": "保存成功", "tts": settings}


@router.get("/voices", summary="可用音色列表")
async def list_voices(
    _=Depends(require_admin),
    service: TTSService = Depends(get_tts_service),
):
    return service.list_voices()


@router.post("/synthesize", summary="试听合成")
async def synthesize(
    payload: SynthesizeRequest,
    _=Depends(require_admin),
    service: TTSService = Depends(get_tts_service),
):
    path = await service.synthesize(payload.text, payload.voice)
    if not path:
        if not service.enabled:
            error = "语音功能已停用，请先启用并保存设置"
        elif service.last_error:
            error = service.last_error
        elif service.config.get("tts.engine", "edge") in {"openai", "minimax"}:
            error = "云端语音合成失败，请检查 API 地址、密钥、模型及音色配置或稍后重试"
        else:
            error = "语音合成失败，请检查 edge-tts 是否安装及网络连接"
        return {"success": False, "error": error}
    static_dir = service.config.resolve_path(str(service.config.get("paths.static_dir", "static")))
    try:
        url = "/static/" + str(Path(path).resolve().relative_to(static_dir.resolve())).replace("\\", "/")
    except ValueError:
        url = ""
    return {"success": True, "file_path": path, "url": url}


@router.get("/cache", summary="语音缓存统计")
async def cache_stats(
    _=Depends(require_admin),
    service: TTSService = Depends(get_tts_service),
):
    return service.cache_stats()


@router.post("/cleanup", summary="清理过期语音缓存")
async def cleanup_cache(
    _=Depends(require_admin),
    service: TTSService = Depends(get_tts_service),
):
    removed = await service.cleanup_cache()
    return {"message": "清理完成", "removed": removed}


@router.delete("/cache", summary="清空全部语音缓存")
async def clear_cache(
    _=Depends(require_admin),
    service: TTSService = Depends(get_tts_service),
):
    removed = await service.clear_cache()
    return {"message": "已清空", "removed": removed}
