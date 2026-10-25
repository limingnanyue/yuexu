"""私聊惦记的管理查询；用户开关不会被管理员重新打开。"""

from datetime import timedelta

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exceptions import NotFoundError
from backend.common.utils import now
from backend.database.models import (
    BotAccount,
    MessageLog,
    UserPushRecord,
    UserPushState,
)


class UserPushRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def bootstrap(self) -> int:
        known = set((await self.session.execute(select(UserPushState.bot_id, UserPushState.user_id))).all())
        histories = await self.session.execute(select(
            MessageLog.bot_id, MessageLog.user_id, func.max(MessageLog.created_at),
        ).where(
            MessageLog.scene == "private", MessageLog.direction == "in", MessageLog.user_id != "",
        ).group_by(MessageLog.bot_id, MessageLog.user_id))
        count = 0
        for bot_id, user_id, last_at in histories:
            if (bot_id, user_id) not in known:
                self.session.add(UserPushState(bot_id=bot_id, user_id=user_id, last_message_at=last_at))
                count += 1
        await self.session.flush()
        return count

    async def list_users(self, page=1, page_size=20, keyword=None):
        moment = now()
        day = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        week = day - timedelta(days=day.weekday())
        counts = select(
            UserPushRecord.bot_id, UserPushRecord.user_id,
            func.sum(case((UserPushRecord.send_time >= day, 1), else_=0)).label("day_count"),
            func.count().label("week_count"),
        ).where(UserPushRecord.sent.is_(True), UserPushRecord.send_time >= week).group_by(
            UserPushRecord.bot_id, UserPushRecord.user_id,
        ).subquery()
        statement = select(
            UserPushState, BotAccount.name, counts.c.day_count, counts.c.week_count,
        ).outerjoin(BotAccount, BotAccount.id == UserPushState.bot_id).outerjoin(counts, (
            (counts.c.bot_id == UserPushState.bot_id) & (counts.c.user_id == UserPushState.user_id)
        )).where(UserPushState.chat_type == "private")
        if keyword:
            statement = statement.where(or_(
                UserPushState.user_id.contains(keyword, autoescape=True),
                BotAccount.name.contains(keyword, autoescape=True),
            ))
        total = await self.session.scalar(select(func.count()).select_from(statement.subquery()))
        rows = await self.session.execute(statement.order_by(UserPushState.last_message_at.desc()).limit(page_size).offset((page - 1) * page_size))
        return list(rows), total

    async def list_records(self, page=1, page_size=20, bot_id=None, user_id=None):
        statement = select(UserPushRecord)
        if bot_id:
            statement = statement.where(UserPushRecord.bot_id == bot_id)
        if user_id:
            statement = statement.where(UserPushRecord.user_id == user_id)
        total = await self.session.scalar(select(func.count()).select_from(statement.subquery()))
        records = await self.session.scalars(statement.order_by(UserPushRecord.send_time.desc(), UserPushRecord.id.desc()).limit(page_size).offset((page - 1) * page_size))
        return list(records), total

    async def disable_user(self, bot_id: str, user_id: str):
        state = await self.session.get(UserPushState, (bot_id, user_id))
        if state is None:
            raise NotFoundError("私聊用户不存在")
        await self.session.execute(update(UserPushState).where(
            UserPushState.bot_id == bot_id, UserPushState.user_id == user_id,
        ).values(user_push_switch=False, claim_token=None, claim_until=None,
                 activity_version=UserPushState.activity_version + 1))
        await self.session.refresh(state)
        return state
