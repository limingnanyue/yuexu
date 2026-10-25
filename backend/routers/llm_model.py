"""LLM 模型池管理接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StrictInt

from backend.dependencies import get_llm_service, require_admin, require_owner
from backend.routers.serializers import model_out
from backend.services.llm_service import LLMService

router = APIRouter(prefix="/api/models", tags=["模型配置"])


class ModelPayload(BaseModel):
    name: str | None = None
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: StrictInt | None = Field(default=None, gt=0)
    context_window: StrictInt | None = Field(default=None, gt=0)
    max_output_tokens: StrictInt | None = Field(default=None, gt=0)
    timeout: int | None = None
    extra: dict[str, Any] | None = None
    is_default: bool | None = None
    enabled: bool | None = None


class ModelDiscoveryPayload(BaseModel):
    base_url: str
    api_key: str | None = None
    model_id: str | None = None
    provider: str | None = None
    model_name: str | None = None


def _clean_key(data: dict[str, Any]) -> dict[str, Any]:
    """忽略前端回传的掩码 Key，避免把 ``****`` 写回数据库。"""
    api_key = data.get("api_key")
    if isinstance(api_key, str) and api_key and "***" in api_key:
        data.pop("api_key", None)
    return data


def _model_data(payload: ModelPayload) -> dict[str, Any]:
    return _clean_key({
        key: value for key, value in payload.model_dump(exclude_unset=True).items()
        if value is not None or key in {"context_window", "max_output_tokens"}
    })


@router.get("", summary="模型列表")
async def list_models(
    _=Depends(require_admin),
    service: LLMService = Depends(get_llm_service),
):
    return [model_out(item) for item in await service.list_models()]


@router.post("/discover", summary="获取远端模型与上下文配置")
async def discover_models(
    payload: ModelDiscoveryPayload,
    _=Depends(require_admin),
    service: LLMService = Depends(get_llm_service),
):
    return await service.discover_models(**payload.model_dump())


@router.post("", summary="新增模型")
async def create_model(
    payload: ModelPayload,
    _=Depends(require_admin),
    service: LLMService = Depends(get_llm_service),
):
    data = _model_data(payload)
    model = await service.create_model(data)
    return model_out(model)


@router.put("/{model_id}", summary="更新模型")
async def update_model(
    model_id: str,
    payload: ModelPayload,
    _=Depends(require_admin),
    service: LLMService = Depends(get_llm_service),
):
    data = _model_data(payload)
    model = await service.update_model(model_id, data)
    return model_out(model)


@router.delete("/{model_id}", summary="删除模型")
async def delete_model(
    model_id: str,
    _=Depends(require_admin),
    service: LLMService = Depends(get_llm_service),
):
    await service.delete_model(model_id)
    return {"message": "已删除"}


@router.post("/{model_id}/default", summary="设为默认模型")
async def set_default(
    model_id: str,
    _=Depends(require_admin),
    service: LLMService = Depends(get_llm_service),
):
    model = await service.set_default(model_id)
    return model_out(model)


@router.post("/{model_id}/test", summary="测试模型连通性")
async def test_model(
    model_id: str,
    _=Depends(require_owner),
    service: LLMService = Depends(get_llm_service),
):
    reply = await service.test_model(model_id)
    return {
        "success": reply.success,
        "content": reply.content,
        "latency_ms": reply.latency_ms,
        "error": reply.error,
    }
