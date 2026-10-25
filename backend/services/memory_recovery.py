"""按原日期补提取尚未处理的入站日志；逐条提交，重启后接续。"""

from __future__ import annotations

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.constants import MessageScene, Platform
from backend.common.logger import get_logger
from backend.common.message import BotEvent
from backend.common.utils import now
from backend.database.models import BotAccount, GroupRule, MemoryEntry, MessageLog
from backend.repositories.context_repo import KeyedLockPool
from backend.services.memory_service import MemoryService
from backend.services.memory_support import NOISE_PATTERN, metadata_from_entry

logger = get_logger("yuexu.memory.recovery")
_locks = KeyedLockPool()


async def recover_memories(
    session: AsyncSession, *, limit: int = 100, log_id: str | None = None,
) -> dict[str, int]:
    """仅处理有效账号开启记忆的消息；返回计数，不输出用户内容。"""
    report = {"scanned": 0, "processed": 0, "created": 0, "skipped": 0, "errors": 0}
    service = MemoryService(session)
    if not service.is_enabled():
        return report

    specific = select(GroupRule.enabled_memory).where(
        GroupRule.bot_id == MessageLog.bot_id, GroupRule.group_id == MessageLog.group_id,
    ).limit(1).scalar_subquery()
    shared = select(GroupRule.enabled_memory).where(
        GroupRule.bot_id.is_(None), GroupRule.group_id == MessageLog.group_id,
    ).limit(1).scalar_subquery()
    query = select(
        MessageLog.id, MessageLog.bot_id, MessageLog.platform, MessageLog.scene,
        MessageLog.user_id, MessageLog.group_id, MessageLog.content, MessageLog.created_at,
    ).join(BotAccount, BotAccount.id == MessageLog.bot_id).where(
        MessageLog.memory_processed_at.is_(None), MessageLog.direction == "in", MessageLog.status == "ok",
        MessageLog.scene.in_(("private", "group")), BotAccount.settings["memory"].as_boolean().is_not(False),
        or_(MessageLog.scene != "group", func.coalesce(specific, shared, True)),
    ).order_by(MessageLog.created_at, MessageLog.id).limit(max(0, limit))
    if log_id is not None:
        query = query.where(MessageLog.id == log_id)
    rows = (await session.execute(query)).all()
    await session.commit()

    for row in rows:
        report["scanned"] += 1
        async with _locks.locked(row.id):
            try:
                pending = await session.scalar(select(MessageLog.id).where(
                    MessageLog.id == row.id, MessageLog.memory_processed_at.is_(None),
                ))
                if pending is None:
                    await session.commit()
                    report["skipped"] += 1
                    continue
                text = (row.content or "").strip()
                library_id = await service.resolve_bot_id(row.bot_id)
                existing = await session.scalar(select(MemoryEntry.id).where(
                    MemoryEntry.bot_id == library_id, MemoryEntry.source_message_id == row.id,
                ).limit(1))
                if (existing or not text or not row.user_id or text.startswith(("/", "／"))
                        or NOISE_PATTERN.search(text) or row.scene == "group" and not row.group_id):
                    entries = []
                else:
                    event = BotEvent(
                        bot_id=row.bot_id, platform=Platform(row.platform), scene=MessageScene(row.scene),
                        user_id=row.user_id, group_id=row.group_id, message_id=row.id,
                        timestamp=int(row.created_at.timestamp()),
                    )
                    entries = await service.extract_and_store(
                        event, text, record_date=row.created_at.date().isoformat(), skip_interval=True,
                        strict_extraction=True,
                    )
                    for entry in entries:
                        entry.created_at = row.created_at
                        entry.updated_at = row.created_at
                        try:
                            await service.vector.update_metadata([entry.id], metadata_from_entry(entry))
                        except Exception as exc:
                            logger.warning("历史记忆索引日期更新失败：%s", type(exc).__name__)
                await session.execute(update(MessageLog).where(MessageLog.id == row.id).values(memory_processed_at=now()))
                await session.commit()
                report["processed"] += 1
                report["created"] += len(entries)
                report["skipped"] += not bool(entries)
            except Exception as exc:
                await session.rollback()
                report["errors"] += 1
                logger.warning("历史记忆处理失败：log=%s type=%s", row.id, type(exc).__name__)
    return report
