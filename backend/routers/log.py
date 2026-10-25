"""日志查询接口：消息 / AI / 搜索 / 推送 / 操作日志 + 导出。"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from backend.common.exceptions import NotFoundError
from backend.dependencies import get_log_service, require_admin, require_owner
from backend.routers.serializers import row_out
from backend.services.log_service import LogService

router = APIRouter(prefix="/api/logs", tags=["日志"])

LOG_TYPES = {"message", "ai", "search", "push", "operation"}


@router.get("/{log_type}", summary="分页查询日志")
async def list_logs(
    log_type: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    keyword: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    bot_id: str | None = None,
    scene: str | None = None,
    direction: str | None = None,
    level: str | None = None,
    module: str | None = None,
    task_id: str | None = None,
    success: bool | None = None,
    _=Depends(require_admin),
    service: LogService = Depends(get_log_service),
):
    if log_type not in LOG_TYPES:
        raise NotFoundError(f"未知日志类型：{log_type}")
    items, total = await service.query(
        log_type,
        page=page,
        page_size=page_size,
        keyword=keyword,
        start=start,
        end=end,
        bot_id=bot_id,
        scene=scene,
        direction=direction,
        level=level,
        module=module,
        task_id=task_id,
        success=success,
    )
    return {
        "items": [row_out(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{log_type}/export", summary="导出日志 CSV")
async def export_logs(
    log_type: str,
    keyword: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    _=Depends(require_admin),
    service: LogService = Depends(get_log_service),
):
    if log_type not in LOG_TYPES:
        raise NotFoundError(f"未知日志类型：{log_type}")
    items, _total = await service.query(
        log_type,
        page=1,
        page_size=200,
        keyword=keyword,
        start=start,
        end=end,
    )
    rows: list[dict[str, Any]] = [row_out(item) for item in items]
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    content = "\ufeff" + output.getvalue()
    filename = f"{log_type}_logs_{datetime.now():%Y%m%d_%H%M%S}.csv"
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/cleanup", summary="按保留天数清理日志")
async def cleanup_logs(
    days: int = Query(30, ge=1, le=3650),
    _=Depends(require_owner),
    service: LogService = Depends(get_log_service),
):
    counts = await service.cleanup(days)
    return {"message": "清理完成", "deleted": counts}
