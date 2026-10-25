"""联网搜索设置接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.dependencies import (
    get_search_service,
    get_system_service,
    require_admin,
    require_owner,
)
from backend.services.search_service import SearchService
from backend.services.system_service import SystemService

router = APIRouter(prefix="/api/search", tags=["联网搜索"])


class SearchSettingsRequest(BaseModel):
    enabled: bool | None = None
    provider: str | None = None
    base_url: str | None = None
    endpoint: str | None = None
    api_key: str | None = None
    top_k: int | None = None
    max_summary_chars: int | None = None
    timeout: int | None = None
    auto_trigger: bool | None = None


class SearchTestRequest(BaseModel):
    query: str


@router.get("/settings", summary="读取搜索配置")
async def get_settings(
    _=Depends(require_admin),
    system: SystemService = Depends(get_system_service),
):
    data = system.public_config().get("search", {})
    return {
        "enabled": data.get("enabled"),
        "provider": data.get("provider"),
        "base_url": data.get("base_url"),
        "endpoint": data.get("endpoint"),
        "api_key": data.get("api_key"),
        "top_k": data.get("top_k"),
        "max_summary_chars": data.get("max_summary_chars"),
        "timeout": data.get("timeout"),
        "auto_trigger": data.get("auto_trigger"),
        "freshness_keywords": data.get("freshness_keywords", []),
    }


@router.put("/settings", summary="更新搜索配置")
async def update_settings(
    payload: SearchSettingsRequest,
    _=Depends(require_owner),
    system: SystemService = Depends(get_system_service),
):
    patch = payload.model_dump(exclude_none=True)
    system.update_config({"search": patch})
    return {"message": "保存成功", "search": {k: v for k, v in patch.items() if k != "api_key"}}


@router.post("/test", summary="测试搜索")
async def test_search(
    payload: SearchTestRequest,
    _=Depends(require_admin),
    service: SearchService = Depends(get_search_service),
):
    result = await service.search(payload.query, trigger_mode="command")
    return {
        "success": result.success,
        "query": result.query,
        "summary": result.summary,
        "items": [item.__dict__ for item in result.items],
        "latency_ms": result.latency_ms,
        "error": result.error,
    }
