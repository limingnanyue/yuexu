"""API 输出序列化工具：ORM 对象 -> JSON 可序列化字典。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.common.crypto import mask_secret
from backend.database.models import LlmModel


def dt(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def row_out(obj: Any, *, exclude: set[str] | None = None) -> dict[str, Any]:
    """按表字段输出，自动处理时间类型。"""
    exclude = exclude or set()
    result: dict[str, Any] = {}
    for column in obj.__table__.columns:
        name = column.name
        if name in exclude:
            continue
        value = getattr(obj, name, None)
        if isinstance(value, datetime):
            value = dt(value)
        result[name] = value
    return result


def emoji_out(item: Any) -> dict[str, Any]:
    """表情输出：补充可访问的静态资源 URL。"""
    data = row_out(item)
    data["url"] = static_url(item.file_path)
    return data


def static_url(file_path: str | None) -> str:
    """把 static 目录下的本地路径转换为 /static/... 访问地址。"""
    if not file_path:
        return ""
    try:
        from pathlib import Path

        from backend.core.config_loader import get_config

        config = get_config()
        static_dir = config.resolve_path(
            str(config.get("paths.static_dir", "static"))
        ).resolve()
        path = Path(file_path)
        if not path.is_absolute():
            path = config.root / path
        relative = path.resolve().relative_to(static_dir)
        return "/static/" + str(relative).replace("\\", "/")
    except (ValueError, OSError):
        return ""


def model_out(model: LlmModel) -> dict[str, Any]:
    """模型配置输出：API Key 只返回掩码。"""
    data = row_out(model)
    data["api_key"] = mask_secret(model.api_key)
    data["has_api_key"] = bool(model.api_key)
    data["context_window"] = (model.extra or {}).get("context_window")
    data["max_output_tokens"] = (model.extra or {}).get("max_output_tokens")
    return data


def task_out(task: Any) -> dict[str, Any]:
    data = row_out(task)
    data["trigger_label"] = {
        "delay": "延时推送",
        "cron": "定时推送",
        "interval": "循环推送",
    }.get(task.trigger_type, task.trigger_type)
    data["target_label"] = "群聊" if task.target_type == "group" else "私聊"
    return data
