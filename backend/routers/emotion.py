"""情感状态管理接口：查看 / 校准 / 重置每段关系的情感状态。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.dependencies import get_emotion_service, require_admin
from backend.routers.serializers import row_out
from backend.services.emotion_service import EmotionService, relationship_stage

router = APIRouter(prefix="/api/emotions", tags=["情感系统"])


def state_out(state: Any) -> dict[str, Any]:
    data = row_out(state)
    data["relationship_stage"] = relationship_stage(state.affection)
    return data


class EmotionPayload(BaseModel):
    mood_label: str | None = Field(None, max_length=32)
    mood_note: str | None = Field(None, max_length=255)
    affection: float | None = Field(None, ge=0, le=100)
    trust: float | None = Field(None, ge=0, le=100)
    current_activity: str | None = Field(None, max_length=128)
    last_event: str | None = Field(None, max_length=255)


@router.get("", summary="情感状态列表")
async def list_emotions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    _=Depends(require_admin),
    service: EmotionService = Depends(get_emotion_service),
):
    items, total = await service.list_page(page, page_size, keyword)
    return {
        "items": [state_out(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{state_id}", summary="情感状态详情")
async def get_emotion(
    state_id: str,
    _=Depends(require_admin),
    service: EmotionService = Depends(get_emotion_service),
):
    return state_out(await service.get_by_id(state_id))


@router.put("/{state_id}", summary="校准情感状态")
async def update_emotion(
    state_id: str,
    payload: EmotionPayload,
    _=Depends(require_admin),
    service: EmotionService = Depends(get_emotion_service),
):
    return state_out(await service.adjust(state_id, payload.model_dump(exclude_none=True)))


@router.delete("/{state_id}", summary="重置情感状态")
async def reset_emotion(
    state_id: str,
    _=Depends(require_admin),
    service: EmotionService = Depends(get_emotion_service),
):
    await service.reset(state_id)
    return {"message": "已重置，下次对话将重新开始积累"}


@router.post("/clear", summary="清空全部情感状态")
async def clear_emotions(
    _=Depends(require_admin),
    service: EmotionService = Depends(get_emotion_service),
):
    count = await service.clear_all()
    return {"message": f"已清空 {count} 条情感状态"}
