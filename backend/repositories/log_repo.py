"""日志数据访问：消息日志、AI 日志、搜索日志、推送日志、操作日志。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import (
    AiRequestLog,
    MessageLog,
    OperationLog,
    PushLog,
    SearchLog,
)


class LogRepo:
    """五类日志统一读写入口。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    async def add_message(
        self,
        *,
        bot_id: str = "",
        platform: str = "",
        scene: str = "private",
        group_id: str | None = None,
        user_id: str = "",
        nickname: str = "",
        direction: str = "in",
        content: str = "",
        segments: list | None = None,
        status: str = "ok",
        error: str | None = None,
    ) -> MessageLog:
        log = MessageLog(
            bot_id=bot_id,
            platform=platform,
            scene=scene,
            group_id=group_id,
            user_id=user_id,
            nickname=nickname,
            direction=direction,
            content=content,
            segments=segments,
            status=status,
            error=error,
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def add_ai(
        self,
        *,
        bot_id: str,
        scene: str,
        group_id: str | None,
        user_id: str,
        model_id: str | None,
        model_name: str,
        prompt_preview: str = "",
        response_preview: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
        success: bool = True,
        error: str | None = None,
    ) -> AiRequestLog:
        log = AiRequestLog(
            bot_id=bot_id,
            scene=scene,
            group_id=group_id,
            user_id=user_id,
            model_id=model_id,
            model_name=model_name,
            prompt_preview=prompt_preview,
            response_preview=response_preview,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            success=success,
            error=error,
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def add_search(
        self,
        *,
        bot_id: str,
        user_id: str,
        query: str,
        provider: str,
        trigger_mode: str,
        result_count: int = 0,
        latency_ms: int = 0,
        success: bool = True,
        error: str | None = None,
        summary_preview: str = "",
    ) -> SearchLog:
        log = SearchLog(
            bot_id=bot_id,
            user_id=user_id,
            query=query,
            provider=provider,
            trigger_mode=trigger_mode,
            result_count=result_count,
            latency_ms=latency_ms,
            success=success,
            error=error,
            summary_preview=summary_preview,
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def add_push(
        self,
        *,
        task_id: str,
        bot_id: str,
        target_type: str,
        target_id: str,
        success: bool,
        error: str | None = None,
    ) -> PushLog:
        log = PushLog(
            task_id=task_id,
            bot_id=bot_id,
            target_type=target_type,
            target_id=target_id,
            success=success,
            error=error,
        )
        self.session.add(log)
        await self.session.flush()
        return log

    async def add_operation(
        self,
        *,
        level: str = "info",
        module: str = "system",
        action: str = "",
        detail: str = "",
        user_id: str | None = None,
        ip: str | None = None,
    ) -> OperationLog:
        log = OperationLog(
            level=level,
            module=module,
            action=action,
            detail=detail,
            user_id=user_id,
            ip=ip,
        )
        self.session.add(log)
        await self.session.flush()
        return log

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def _query(
        self,
        model: Any,
        *,
        page: int,
        page_size: int,
        conditions: Sequence[Any],
    ) -> tuple[list[Any], int]:
        count_stmt = select(func.count()).select_from(model)
        stmt = select(model)
        if conditions:
            count_stmt = count_stmt.where(*conditions)
            stmt = stmt.where(*conditions)
        total = int(await self.session.scalar(count_stmt) or 0)
        stmt = (
            stmt.order_by(model.created_at.desc())
            .limit(max(1, page_size))
            .offset((max(page, 1) - 1) * page_size)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    @staticmethod
    def _conditions(
        model: Any,
        *,
        keyword: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        fields: Sequence[str] = (),
        **equals: Any,
    ) -> list[Any]:
        conditions: list[Any] = []
        for key, value in equals.items():
            if value is not None and value != "":
                conditions.append(getattr(model, key) == value)
        if start:
            conditions.append(model.created_at >= start)
        if end:
            conditions.append(model.created_at <= end)
        if keyword and fields:
            pattern = f"%{keyword}%"
            conditions.append(or_(*(getattr(model, field).like(pattern) for field in fields)))
        return conditions

    async def list_messages(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        bot_id: str | None = None,
        scene: str | None = None,
        direction: str | None = None,
        keyword: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[list[MessageLog], int]:
        conditions = self._conditions(
            MessageLog,
            keyword=keyword,
            start=start,
            end=end,
            fields=("content", "nickname", "user_id", "group_id"),
            bot_id=bot_id,
            scene=scene,
            direction=direction,
        )
        return await self._query(MessageLog, page=page, page_size=page_size, conditions=conditions)

    async def list_ai(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        bot_id: str | None = None,
        success: bool | None = None,
        keyword: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[list[AiRequestLog], int]:
        conditions = self._conditions(
            AiRequestLog,
            keyword=keyword,
            start=start,
            end=end,
            fields=("prompt_preview", "response_preview", "model_name", "user_id"),
            bot_id=bot_id,
            success=success,
        )
        return await self._query(AiRequestLog, page=page, page_size=page_size, conditions=conditions)

    async def list_search(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        bot_id: str | None = None,
        keyword: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[list[SearchLog], int]:
        conditions = self._conditions(
            SearchLog,
            keyword=keyword,
            start=start,
            end=end,
            fields=("query", "summary_preview"),
            bot_id=bot_id,
        )
        return await self._query(SearchLog, page=page, page_size=page_size, conditions=conditions)

    async def list_push(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        task_id: str | None = None,
        success: bool | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[list[PushLog], int]:
        conditions = self._conditions(
            PushLog, start=start, end=end, task_id=task_id, success=success
        )
        return await self._query(PushLog, page=page, page_size=page_size, conditions=conditions)

    async def list_operations(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        module: str | None = None,
        level: str | None = None,
        keyword: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple[list[OperationLog], int]:
        conditions = self._conditions(
            OperationLog,
            keyword=keyword,
            start=start,
            end=end,
            fields=("action", "detail"),
            module=module,
            level=level,
        )
        return await self._query(
            OperationLog, page=page, page_size=page_size, conditions=conditions
        )

    # ------------------------------------------------------------------
    # 统计 / 清理
    # ------------------------------------------------------------------
    async def count_since(self, model: Any, since: datetime, **filters: Any) -> int:
        conditions = [model.created_at >= since]
        for key, value in filters.items():
            if value is not None:
                conditions.append(getattr(model, key) == value)
        stmt = select(func.count()).select_from(model).where(*conditions)
        return int(await self.session.scalar(stmt) or 0)

    async def cleanup_before(self, moment: datetime) -> dict[str, int]:
        """删除指定时间之前的日志，返回各表删除数量。"""
        result: dict[str, int] = {}
        for name, model in (
            ("message", MessageLog),
            ("ai", AiRequestLog),
            ("search", SearchLog),
            ("push", PushLog),
            ("operation", OperationLog),
        ):
            conditions = [model.created_at < moment]
            if model is MessageLog:
                # 未完成记忆抽取的入站消息也是持久任务，完成后再按保留期清理。
                conditions.append(or_(
                    MessageLog.direction != "in", MessageLog.status != "ok",
                    MessageLog.memory_processed_at.is_not(None),
                ))
            session_result = await self.session.execute(
                model.__table__.delete().where(*conditions)
            )
            result[name] = int(session_result.rowcount or 0)
        await self.session.flush()
        return result
