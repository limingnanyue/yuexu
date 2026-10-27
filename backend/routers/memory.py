"""长期记忆管理接口（4.5 优化版）：检索、确认/否认、配置与维护。"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from backend.dependencies import (
    get_memory_service,
    get_system_service,
    require_admin,
)
from backend.routers.serializers import row_out
from backend.services.memory_service import MemoryService
from backend.services.system_service import SystemService

router = APIRouter(prefix="/api/memory", tags=["记忆管理"])

LibraryId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]

# 允许通过后台修改的记忆参数（不含密钥；embedding 为整段 dict 深合并）
_SETTING_KEYS = {
    "enabled",
    "backend",
    "top_k",
    "coarse_top_k",
    "max_prompt_chars",
    "max_entry_chars",
    "extract_interval",
    "fuzzy_enabled",
    "precise_threshold",
    "fuzzy_threshold",
    "precise_max_fuzzy_weight",
    "fuzzy_keywords",
    "fuzzy_llm_confirm",
    "recall_cache_ttl",
    "rerank_enabled",
    "rerank_weights",
    "precise_timeout_ms",
    "fuzzy_timeout_ms",
    "breaker_failures",
    "breaker_cooldown",
    "max_concurrency",
    "hot_days",
    "warm_days",
    "hot_score_init",
    "hot_hit_boost",
    "denied_penalty",
    "hot_decay",
    "feedback_auto",
    "write_async",
    "llm_extract",
    "extract_timeout",
    "dedupe_threshold",
    "supersede_enabled",
    "recall_reinforce",
    "recall_reinforce_boost",
    "recall_reinforce_interval",
    "auto_purge_cold",
    "cold_purge_days",
    "cold_purge_hot_below",
    "group_shared_enabled",
    "group_shared_extract",
    "global_enabled",
    "hnsw_search_ef",
    "hnsw_construction_ef",
    "embedding",
}


class MemoryResetRequest(BaseModel):
    bot_id: str
    library_id: LibraryId | None = None
    scope_type: str | None = None
    group_id: str | None = None


class MemoryIdsRequest(BaseModel):
    ids: list[str] = Field(min_length=1)


class MaintenanceRequest(BaseModel):
    action: str


class MemoryEditRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    content: str = Field(min_length=1)
    memory_type: Literal["fact", "preference", "plan"] = "fact"
    tag_keywords: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    ] = Field(default_factory=list, max_length=20)


class MemoryCreateRequest(MemoryEditRequest):
    bot_id: str = Field(min_length=1, max_length=40)
    library_id: LibraryId | None = None
    user_id: str = Field(default="", max_length=64)
    scope_type: Literal["private", "group", "group_shared", "global"] = "private"
    group_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_scope(self):
        if self.scope_type in {"group", "group_shared"} and not self.group_id:
            raise ValueError("群聊 / 群共享记忆必须填写群号")
        if self.scope_type in {"private", "global"} and self.group_id is not None:
            raise ValueError("私聊 / 全局记忆不能填写群号")
        if self.scope_type in {"private", "group"} and not self.user_id:
            raise ValueError("私聊 / 群聊记忆必须填写用户 ID")
        return self


def _memory_out(service: MemoryService, entry) -> dict[str, Any]:  # noqa: ANN001
    data = row_out(entry)
    data["tier"] = service.tier_of(entry)
    data["tag_keywords"] = entry.tag_keywords or []
    return data


@router.get("", summary="检索用户记忆")
async def list_memories(
    bot_id: str = Query(..., description="机器人账号 ID"),
    library_id: LibraryId | None = Query(None, description="直接选择记忆库，优先于账号绑定"),
    user_id: str | None = Query(None, description="用户 ID，留空浏览该账号的所有用户"),
    scope_type: str | None = None,
    group_id: str | None = None,
    keyword: str | None = None,
    memory_type: str | None = None,
    rejected: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    target_type: str | None = Query(None, description="分区：user / group / global"),
    _=Depends(require_admin),
    service: MemoryService = Depends(get_memory_service),
):
    items, total = await service.list_entries(
        bot_id,
        user_id,
        page=page,
        page_size=page_size,
        scope_type=scope_type,
        group_id=group_id,
        target_type=target_type,
        keyword=keyword,
        memory_type=memory_type,
        rejected=rejected,
        library_id=library_id,
    )
    return {
        "items": [_memory_out(service, item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("", summary="手工添加记忆")
async def create_memory(
    payload: MemoryCreateRequest,
    _=Depends(require_admin),
    service: MemoryService = Depends(get_memory_service),
):
    entry = await service.create_entry(**payload.model_dump())
    return _memory_out(service, entry)


@router.get("/stats", summary="记忆统计（冷热 / 类型 / 否定）")
async def memory_stats(
    bot_id: str | None = None,
    library_id: LibraryId | None = Query(None),
    _=Depends(require_admin),
    service: MemoryService = Depends(get_memory_service),
):
    return await service.stats(bot_id, library_id=library_id)


@router.get("/settings", summary="读取记忆库参数")
async def get_memory_settings(
    _=Depends(require_admin),
    system: SystemService = Depends(get_system_service),
):
    data = system.public_config().get("memory", {})
    return {key: value for key, value in data.items() if key in _SETTING_KEYS}


@router.put("/settings", summary="更新记忆库参数")
async def update_memory_settings(
    payload: dict[str, Any] = Body(...),
    _=Depends(require_admin),
    system: SystemService = Depends(get_system_service),
):
    patch = {key: value for key, value in payload.items() if key in _SETTING_KEYS}
    if not patch:
        return {"message": "没有可更新的参数", "memory": {}}
    system.update_config({"memory": patch})
    return {"message": "保存成功，部分参数需重启或下一轮对话生效", "memory": patch}


@router.get("/export", summary="导出记忆")
async def export_memory(
    bot_id: str = Query(...),
    library_id: LibraryId | None = Query(None),
    user_id: str | None = None,
    scope_type: str | None = None,
    group_id: str | None = None,
    keyword: str | None = None,
    memory_type: str | None = None,
    rejected: bool | None = None,
    _=Depends(require_admin),
    service: MemoryService = Depends(get_memory_service),
):
    return await service.export(
        bot_id, user_id, scope_type=scope_type, group_id=group_id,
        keyword=keyword, memory_type=memory_type, rejected=rejected,
        library_id=library_id,
    )


@router.post("/confirm", summary="确认记忆（转正 / 提升置信度）")
async def confirm_memories(
    payload: MemoryIdsRequest,
    _=Depends(require_admin),
    service: MemoryService = Depends(get_memory_service),
):
    count = await service.confirm(payload.ids)
    return {"message": "已确认", "updated": count}


@router.post("/reject", summary="否认记忆（降热度 / 永久屏蔽）")
async def reject_memories(
    payload: MemoryIdsRequest,
    _=Depends(require_admin),
    service: MemoryService = Depends(get_memory_service),
):
    count = await service.reject(payload.ids)
    return {"message": "已屏蔽", "updated": count}


@router.post("/reset", summary="批量重置记忆")
async def reset_memory(
    payload: MemoryResetRequest,
    _=Depends(require_admin),
    service: MemoryService = Depends(get_memory_service),
):
    count = await service.reset(
        payload.bot_id, scope_type=payload.scope_type, group_id=payload.group_id,
        library_id=payload.library_id,
    )
    return {"message": "已重置", "deleted": count}


@router.post("/maintenance", summary="立即执行维护任务")
async def run_maintenance(
    payload: MaintenanceRequest,
    _=Depends(require_admin),
    service: MemoryService = Depends(get_memory_service),
):
    action = payload.action.lower()
    if action == "decay":
        affected = await service.decay_all()
    elif action == "dedupe":
        affected = await service.dedupe_all()
    elif action == "purge":
        affected = await service.purge_cold(force=True)
    elif action == "gc":
        affected = await service.gc_vectors()
    elif action == "reindex":
        affected = await service.reindex()
    else:
        return {"message": f"未知维护动作：{action}", "affected": 0}
    return {"message": "执行完成", "action": action, "affected": affected}


@router.put("/{memory_id}", summary="更正记忆内容、类型和关键词")
async def update_memory(
    memory_id: str,
    payload: MemoryEditRequest,
    _=Depends(require_admin),
    service: MemoryService = Depends(get_memory_service),
):
    entry = await service.update_entry(memory_id, **payload.model_dump())
    return _memory_out(service, entry)


@router.delete("/{memory_id}", summary="删除单条记忆")
async def delete_memory(
    memory_id: str,
    _=Depends(require_admin),
    service: MemoryService = Depends(get_memory_service),
):
    await service.delete(memory_id)
    return {"message": "已删除"}
