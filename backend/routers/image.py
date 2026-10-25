"""生图模型设置和测试接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator

from backend.common.utils import mask_secret
from backend.dependencies import get_image_service, get_system_service, require_admin
from backend.services.image_service import (
    MAX_PROMPT_CHARS,
    ImageService,
    validate_settings,
)
from backend.services.system_service import SystemService

router = APIRouter(prefix="/api/images", tags=["AI 生图"])


class ImageSettingsRequest(BaseModel):
    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = Field(default=None, max_length=1024)
    model: str | None = Field(default=None, max_length=1024)
    size: str | None = None
    timeout: int | None = Field(default=None, ge=1, le=600, strict=True)
    cache_ttl_hours: int | None = Field(default=None, ge=0, le=8760, strict=True)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    size: str | None = Field(default=None, pattern=r"^(auto|[1-9]\d{1,3}x[1-9]\d{1,3})$")

    @field_validator("prompt")
    @classmethod
    def nonempty_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("提示词不能为空")
        return value.strip()


def _public_settings(service: ImageService, system: SystemService) -> dict:
    settings = system.public_config().get("image_generation", {})
    return {
        **{key: settings.get(key) for key in ImageSettingsRequest.model_fields},
        "api_key": mask_secret(service.config.get("image_generation.api_key", "")),
        "available": service.available,
    }


@router.get("/settings", summary="读取生图模型配置")
async def get_settings(
    _=Depends(require_admin),
    service: ImageService = Depends(get_image_service),
    system: SystemService = Depends(get_system_service),
):
    return _public_settings(service, system)


@router.put("/settings", summary="更新生图模型配置")
async def update_settings(
    payload: ImageSettingsRequest,
    _=Depends(require_admin),
    service: ImageService = Depends(get_image_service),
    system: SystemService = Depends(get_system_service),
):
    patch = payload.model_dump(exclude_none=True)
    current = dict(service.config.section("image_generation"))
    for field in ("base_url", "api_key", "model", "size"):
        if field in patch:
            patch[field] = patch[field].strip()
    patch = system._strip_masks(patch, current)
    if ("base_url" in patch and patch["base_url"].rstrip("/") != str(current.get("base_url", "")).rstrip("/")
            and "api_key" not in patch):
        patch["api_key"] = ""
    validate_settings({**current, **patch})
    system.update_config({"image_generation": patch})
    return {"message": "保存成功", "image_generation": _public_settings(service, system)}


@router.post("/generate", summary="生成图片")
async def generate(
    payload: GenerateRequest,
    _=Depends(require_admin),
    service: ImageService = Depends(get_image_service),
):
    return await service.generate(payload.prompt, payload.size)
