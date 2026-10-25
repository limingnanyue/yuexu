"""活力 Agent 接口：全局参数、会话管理、搭话日志、兜底话题素材库。"""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, field_validator

from backend.common.exceptions import NotFoundError, ValidationError
from backend.common.utils import now
from backend.dependencies import (
    get_vitality_service,
    require_admin,
    require_owner,
)
from backend.repositories.account_repo import AccountRepo
from backend.repositories.vitality_repo import (
    AgentActiveLogRepo,
    SessionActivityRepo,
    TopicBankRepo,
)
from backend.routers.serializers import row_out
from backend.services.vitality_service import VitalityService, classify_sentiment

router = APIRouter(prefix="/api/vitality", tags=["活力Agent"])

_WINDOW_PATTERN = re.compile(r"^\d{1,2}:\d{2}-\d{1,2}:\d{2}$")
_TOPIC_TAGS = {"normal", "memory", "fun", "question"}


class VitalitySettingsRequest(BaseModel):
    enabled: bool | None = None
    interval: int | None = None
    base_threshold: int | None = None
    threshold_min: int | None = None
    threshold_max: int | None = None
    private_cooldown_minutes: int | None = None
    group_cooldown_minutes: int | None = None
    max_hour_sends: int | None = None
    active_window: str | None = None
    reply_window_minutes: int | None = None
    max_sends_per_tick: int | None = None

    @field_validator("active_window")
    @classmethod
    def _valid_window(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not _WINDOW_PATTERN.fullmatch(value):
            raise ValueError("活跃时段格式须为 HH:MM-HH:MM，例如 09:00-23:00")
        for part in value.split("-"):
            hour, minute = (int(piece) for piece in part.split(":"))
            if hour > 23 or minute > 59:
                raise ValueError("活跃时段时间越界")
        return value


class SessionPatchRequest(BaseModel):
    enable_agent: bool | None = None
    is_black: bool | None = None
    dynamic_threshold: int | None = None


class TopicRequest(BaseModel):
    topic_content: str
    tag: str = "normal"
    weight: int = 10
    enable: bool = True

    @field_validator("topic_content")
    @classmethod
    def _valid_content(cls, value: str) -> str:
        value = value.strip()
        if not value or len(value) > 200:
            raise ValueError("话题内容须为 1-200 字")
        return value

    @field_validator("tag")
    @classmethod
    def _valid_tag(cls, value: str) -> str:
        if value not in _TOPIC_TAGS:
            raise ValueError("标签仅支持 normal / memory / fun / question")
        return value

    @field_validator("weight")
    @classmethod
    def _valid_weight(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError("权重须为 1-100")
        return value


class PreviewRequest(BaseModel):
    bot_id: str
    target_type: str
    target_id: str

    @field_validator("target_type")
    @classmethod
    def _valid_type(cls, value: str) -> str:
        if value not in {"private", "group"}:
            raise ValueError("target_type 仅支持 private / group")
        return value


# ---------------------------------------------------------------------------
# 全局参数（能力范围：阈值 / 冷却 / 次数上限 / 活跃时段）
# ---------------------------------------------------------------------------
@router.get("/settings", summary="读取活力 Agent 配置")
async def get_settings(
    _=Depends(require_admin),
    service: VitalityService = Depends(get_vitality_service),
):
    data = service.config.get("vitality", {}) or {}
    return {key: data.get(key) for key in (
        "enabled", "interval", "base_threshold", "threshold_min", "threshold_max",
        "private_cooldown_minutes", "group_cooldown_minutes", "max_hour_sends",
        "active_window", "reply_window_minutes", "max_sends_per_tick",
    )}


@router.put("/settings", summary="更新活力 Agent 配置")
async def update_settings(
    payload: VitalitySettingsRequest,
    _=Depends(require_owner),
    service: VitalityService = Depends(get_vitality_service),
):
    patch = payload.model_dump(exclude_none=True)
    for key, low, high in (
        ("interval", 30, 3600), ("base_threshold", 0, 100),
        ("threshold_min", 0, 100), ("threshold_max", 0, 100),
        ("private_cooldown_minutes", 1, 1440), ("group_cooldown_minutes", 1, 1440),
        ("max_hour_sends", 1, 10), ("reply_window_minutes", 5, 1440),
        ("max_sends_per_tick", 1, 20),
    ):
        if key in patch and not low <= int(patch[key]) <= high:
            raise ValidationError(f"{key} 须在 {low}-{high} 之间")
    data = {**service.config.get("vitality", {}), **patch}
    low, high = int(data.get("threshold_min", 40)), int(data.get("threshold_max", 90))
    if low >= high:
        raise ValidationError("threshold_min 必须小于 threshold_max")
    if not low <= int(data.get("base_threshold", 60)) <= high:
        raise ValidationError("base_threshold 必须在阈值区间内")
    service.config.update({"vitality": patch}, persist=True)
    return {"message": "保存成功", "vitality": patch}


# ---------------------------------------------------------------------------
# 会话管理
# ---------------------------------------------------------------------------
@router.get("/sessions", summary="会话活跃度列表")
async def list_sessions(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    target_type: str | None = None,
    enabled: bool | None = None,
    service: VitalityService = Depends(get_vitality_service),
    _=Depends(require_admin),
):
    filters: dict[str, Any] = {}
    if target_type in {"private", "group"}:
        filters["target_type"] = target_type
    if enabled is not None:
        filters["enable_agent"] = enabled
    repo = SessionActivityRepo(service.session)
    items, total = await repo.paginate(
        page=page, page_size=page_size, order_by="last_msg_time", desc=True, **filters,
    )
    moment = now()
    bot_ids = sorted({item.bot_id for item in items})
    accounts = await AccountRepo(service.session).get_many(bot_ids) if bot_ids else []
    bot_names = {account.id: account.name for account in accounts}
    return {
        "items": [
            {**_session_out(service, item, moment), "bot_name": bot_names.get(item.bot_id, "")}
            for item in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _session_out(service: VitalityService, item: Any, moment: Any) -> dict[str, Any]:
    data = row_out(item)
    data["score"] = service.boredom_score(item, moment)
    data["threshold_bounds"] = list(service.threshold_bounds())
    return data


@router.patch("/sessions/{activity_id}", summary="修改会话开关 / 阈值")
async def patch_session(
    activity_id: str,
    payload: SessionPatchRequest,
    service: VitalityService = Depends(get_vitality_service),
    _=Depends(require_admin),
):
    repo = SessionActivityRepo(service.session)
    activity = await repo.get(activity_id)
    if activity is None:
        raise NotFoundError("会话不存在")
    values = payload.model_dump(exclude_none=True)
    if "dynamic_threshold" in values:
        low, high = service.threshold_bounds()
        if not low <= int(values["dynamic_threshold"]) <= high:
            raise ValidationError(f"阈值须在 {low}-{high} 之间")
    return _session_out(service, await repo.update(activity, **values), now())


# ---------------------------------------------------------------------------
# 搭话日志
# ---------------------------------------------------------------------------
@router.get("/logs", summary="主动搭话日志")
async def list_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    target_type: str | None = None,
    target_id: str | None = None,
    status: str | None = None,
    service: VitalityService = Depends(get_vitality_service),
    _=Depends(require_admin),
):
    filters: dict[str, Any] = {}
    if target_type in {"private", "group"}:
        filters["target_type"] = target_type
    if target_id:
        filters["target_id"] = target_id.strip()
    if status:
        filters["status"] = status.strip()
    repo = AgentActiveLogRepo(service.session)
    items, total = await repo.paginate(page=page, page_size=page_size, **filters)
    return {
        "items": [row_out(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# 兜底话题素材库
# ---------------------------------------------------------------------------
@router.get("/topics", summary="话题素材列表")
async def list_topics(
    service: VitalityService = Depends(get_vitality_service),
    _=Depends(require_admin),
):
    repo = TopicBankRepo(service.session)
    items = await repo.list(limit=500, order_by="created_at", desc=True)
    return {"items": [row_out(item) for item in items], "total": len(items)}


@router.post("/topics", summary="新增话题素材")
async def create_topic(
    payload: TopicRequest,
    service: VitalityService = Depends(get_vitality_service),
    _=Depends(require_owner),
):
    repo = TopicBankRepo(service.session)
    topic = await repo.create(**payload.model_dump())
    return {"message": "已添加", "topic": row_out(topic)}


@router.put("/topics/{topic_id}", summary="修改话题素材")
async def update_topic(
    topic_id: str,
    payload: TopicRequest,
    service: VitalityService = Depends(get_vitality_service),
    _=Depends(require_owner),
):
    repo = TopicBankRepo(service.session)
    topic = await repo.get(topic_id)
    if topic is None:
        raise NotFoundError("素材不存在")
    return {"message": "已保存", "topic": row_out(await repo.update(topic, **payload.model_dump()))}


@router.delete("/topics/{topic_id}", summary="删除话题素材")
async def delete_topic(
    topic_id: str,
    service: VitalityService = Depends(get_vitality_service),
    _=Depends(require_owner),
):
    repo = TopicBankRepo(service.session)
    topic = await repo.get(topic_id)
    if topic is None:
        raise NotFoundError("素材不存在")
    await repo.delete(topic)
    return {"message": "已删除"}


# ---------------------------------------------------------------------------
# 预览（生成但不发送）
# ---------------------------------------------------------------------------
@router.post("/preview", summary="预览一次主动搭话（不发送）")
async def preview(
    payload: PreviewRequest,
    service: VitalityService = Depends(get_vitality_service),
    _=Depends(require_admin),
):
    result = await service.preview(payload.bot_id, payload.target_type, payload.target_id)
    return result


# ---------------------------------------------------------------------------
# 情绪分类自检（调试用）
# ---------------------------------------------------------------------------
@router.get("/sentiment", summary="测试回复情绪分类")
async def test_sentiment(
    text: str = Query(..., min_length=1, max_length=200),
    _=Depends(require_admin),
):
    return {"text": text, "sentiment": classify_sentiment(text) or "none"}
