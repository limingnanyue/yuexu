"""日志服务：统一查询、导出、清理入口（写入由各业务服务通过 LogRepo 完成）。"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.logger import get_logger
from backend.repositories.log_repo import LogRepo

logger = get_logger("yuexu.service.log")


class LogService:
    """日志查询门面。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = LogRepo(session)

    async def query(
        self,
        log_type: str,
        *,
        page: int = 1,
        page_size: int = 20,
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
    ) -> tuple[list[Any], int]:
        common = {"page": page, "page_size": page_size, "keyword": keyword,
                  "start": start, "end": end}
        if log_type == "message":
            return await self.repo.list_messages(
                **common, bot_id=bot_id, scene=scene, direction=direction
            )
        if log_type == "ai":
            return await self.repo.list_ai(**common, bot_id=bot_id, success=success)
        if log_type == "search":
            return await self.repo.list_search(**common, bot_id=bot_id)
        if log_type == "push":
            return await self.repo.list_push(
                page=page, page_size=page_size, task_id=task_id,
                success=success, start=start, end=end,
            )
        if log_type == "operation":
            return await self.repo.list_operations(
                page=page, page_size=page_size, keyword=keyword,
                start=start, end=end, level=level, module=module,
            )
        raise ValueError(f"未知日志类型：{log_type}")

    async def cleanup(self, retention_days: int) -> dict[str, int]:
        if retention_days <= 0:
            return {}
        moment = datetime.now() - timedelta(days=retention_days)
        counts = await self.repo.cleanup_before(moment)
        logger.info("日志清理完成（保留 %s 天）：%s", retention_days, counts)
        return counts

    async def log_operation(
        self,
        action: str,
        *,
        module: str = "system",
        detail: str = "",
        level: str = "info",
        user_id: str | None = None,
        ip: str | None = None,
    ) -> None:
        await self.repo.add_operation(
            level=level, module=module, action=action, detail=detail,
            user_id=user_id, ip=ip,
        )
