"""人设管理接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from backend.dependencies import get_character_service, require_admin
from backend.routers.serializers import row_out
from backend.services.character_service import CharacterService

router = APIRouter(prefix="/api/characters", tags=["人设管理"])


class CharacterPayload(BaseModel):
    name: str | None = None
    description: str | None = None
    personality: str | None = None
    speaking_style: str | None = None
    background: str | None = None
    hobbies: str | None = None
    social_circle: str | None = None
    life_schedule: list[dict[str, Any]] | None = None
    taboos: str | None = None
    red_lines: str | None = None
    system_prompt_template: str | None = None
    style_settings: dict[str, Any] | None = None
    emoji_keys: list[str] | None = None
    scope: str | None = None
    is_default: bool | None = None
    enabled: bool | None = None


@router.get("", summary="人设列表")
async def list_characters(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    _=Depends(require_admin),
    service: CharacterService = Depends(get_character_service),
):
    items, total = await service.list_page(page, page_size, keyword)
    return {
        "items": [row_out(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/default", summary="获取默认人设")
async def get_default(
    _=Depends(require_admin),
    service: CharacterService = Depends(get_character_service),
):
    character = await service.get_default()
    return row_out(character) if character else None


@router.post("", summary="新建人设")
async def create_character(
    payload: CharacterPayload,
    _=Depends(require_admin),
    service: CharacterService = Depends(get_character_service),
):
    character = await service.create(payload.model_dump(exclude_none=True))
    return row_out(character)


@router.get("/{character_id}", summary="人设详情")
async def get_character(
    character_id: str,
    _=Depends(require_admin),
    service: CharacterService = Depends(get_character_service),
):
    return row_out(await service.get(character_id))


@router.put("/{character_id}", summary="更新人设")
async def update_character(
    character_id: str,
    payload: CharacterPayload,
    _=Depends(require_admin),
    service: CharacterService = Depends(get_character_service),
):
    character = await service.update(character_id, payload.model_dump(exclude_none=True))
    return row_out(character)


@router.delete("/{character_id}", summary="删除人设")
async def delete_character(
    character_id: str,
    _=Depends(require_admin),
    service: CharacterService = Depends(get_character_service),
):
    await service.delete(character_id)
    return {"message": "已删除"}


@router.post("/{character_id}/default", summary="设为默认人设")
async def set_default(
    character_id: str,
    _=Depends(require_admin),
    service: CharacterService = Depends(get_character_service),
):
    return row_out(await service.set_default(character_id))


@router.get("/{character_id}/preview", summary="预览 System Prompt")
async def preview_prompt(
    character_id: str,
    _=Depends(require_admin),
    service: CharacterService = Depends(get_character_service),
):
    return await service.preview(character_id)


@router.get("/{character_id}/export", summary="导出人设模板")
async def export_character(
    character_id: str,
    _=Depends(require_admin),
    service: CharacterService = Depends(get_character_service),
):
    return await service.export_character(character_id)


@router.post("/import", summary="导入人设模板")
async def import_character(
    payload: dict[str, Any],
    _=Depends(require_admin),
    service: CharacterService = Depends(get_character_service),
):
    character = await service.import_character(payload)
    return row_out(character)
