"""活力 Agent 数据访问：会话活跃度、主动搭话日志、兜底话题素材库。"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.models import AgentActiveLog, AgentTopicBank, SessionActivity
from backend.repositories.base import BaseRepository


class SessionActivityRepo(BaseRepository):
    """会话活跃度表（唯一键：bot_id + target_type + target_id）。"""

    model = SessionActivity

    async def get_activity(
        self, bot_id: str, target_type: str, target_id: str
    ) -> SessionActivity | None:
        return await self.session.scalar(select(SessionActivity).where(
            SessionActivity.bot_id == bot_id,
            SessionActivity.target_type == target_type,
            SessionActivity.target_id == target_id,
        ))

    async def get_or_create(
        self,
        bot_id: str,
        target_type: str,
        target_id: str,
        *,
        base_threshold: int = 60,
    ) -> SessionActivity:
        activity = await self.get_activity(bot_id, target_type, target_id)
        if activity is not None:
            return activity
        try:
            async with self.session.begin_nested():
                activity = await self.create(
                    bot_id=bot_id,
                    target_type=target_type,
                    target_id=target_id,
                    dynamic_threshold=base_threshold,
                )
        except IntegrityError:
            # 并发写入时唯一键冲突：读回已存在行
            activity = await self.get_activity(bot_id, target_type, target_id)
        return activity

    async def list_candidates(self, *, limit: int = 100) -> list[SessionActivity]:
        """轮询候选：开启活力 Agent 且未拉黑的会话，最久未轮询优先。"""
        return list((await self.session.scalars(select(SessionActivity).where(
            SessionActivity.enable_agent.is_(True),
            SessionActivity.is_black.is_(False),
        ).order_by(
            SessionActivity.last_agent_send_time.asc().nullsfirst(),
        ).limit(limit))).all())

    async def touch_message(
        self, activity_id: str, moment: datetime
    ) -> None:
        await self.session.execute(update(SessionActivity).where(
            SessionActivity.id == activity_id,
        ).values(last_msg_time=moment))


class AgentActiveLogRepo(BaseRepository):
    """主动搭话日志表（BigInteger 自增主键）。"""

    model = AgentActiveLog

    async def add_log(self, **values: Any) -> AgentActiveLog:
        return await self.create(**values)

    async def latest_unanswered(
        self,
        bot_id: str,
        target_type: str,
        target_id: str,
        *,
        within: timedelta,
        moment: datetime,
    ) -> AgentActiveLog | None:
        """最近一条已发送且尚未回填回复的日志（用于用户回复归属）。"""
        return await self.session.scalar(select(AgentActiveLog).where(
            AgentActiveLog.bot_id == bot_id,
            AgentActiveLog.target_type == target_type,
            AgentActiveLog.target_id == target_id,
            AgentActiveLog.status == "success",
            AgentActiveLog.user_reply_sentiment == "",
            AgentActiveLog.created_at <= moment,
            AgentActiveLog.created_at >= moment - within,
        ).order_by(
            AgentActiveLog.created_at.desc(), AgentActiveLog.id.desc(),
        ).limit(1))

    async def expire_unanswered(
        self, *, before: datetime, limit: int = 100
    ) -> list[AgentActiveLog]:
        """超过回填窗口仍未回复的日志（回填 none 情绪）。"""
        return list((await self.session.scalars(select(AgentActiveLog).where(
            AgentActiveLog.status == "success",
            AgentActiveLog.user_reply_sentiment == "",
            AgentActiveLog.created_at < before,
        ).order_by(AgentActiveLog.created_at.asc()).limit(limit))).all())

    async def count_hour_sends(
        self, bot_id: str, target_type: str, target_id: str, *, since: datetime
    ) -> int:
        return int(await self.session.scalar(select(func.count()).select_from(
            AgentActiveLog
        ).where(
            AgentActiveLog.bot_id == bot_id,
            AgentActiveLog.target_type == target_type,
            AgentActiveLog.target_id == target_id,
            AgentActiveLog.status == "success",
            AgentActiveLog.created_at >= since,
        )) or 0)


class TopicBankRepo(BaseRepository):
    """兜底话题素材库。"""

    model = AgentTopicBank

    async def pick_random(self, *, exclude_contents: list[str] | None = None) -> AgentTopicBank | None:
        """按权重随机取一条启用素材；exclude_contents 用于避免短期重复。"""
        rows = list((await self.session.scalars(select(AgentTopicBank).where(
            AgentTopicBank.enable.is_(True),
        ))).all())
        rows = [row for row in rows if row.topic_content not in set(exclude_contents or [])]
        if not rows:
            return None
        weights = [max(1, int(row.weight or 1)) for row in rows]
        return random.choices(rows, weights=weights, k=1)[0]
