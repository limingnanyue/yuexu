"""管理员显式恢复旧日志；启动与定时任务不会自动重建已清除的上下文。"""

from sqlalchemy import select

from backend.common.constants import (
    CMD_CLEAR_CONTEXT,
    group_session_key,
    private_session_key,
)
from backend.database.models import BotAccount, MessageLog
from backend.services.llm_service import LLMService


async def restore_contexts_from_logs(context_service, session, *, private_only: bool = True) -> dict[str, int]:
    """恢复缺失的会话及完整原文，保留原时间、隔离维度与已有快照。"""
    query = select(MessageLog).join(BotAccount, BotAccount.id == MessageLog.bot_id).where(
        MessageLog.status == "ok", MessageLog.direction.in_(("in", "out")),
        MessageLog.scene.in_(("private",) if private_only else ("private", "group")),
    ).order_by(MessageLog.created_at, MessageLog.id)
    rows = (await session.scalars(query)).all()
    grouped: dict[str, dict] = {}
    skipped = 0
    for row in rows:
        if not row.user_id or not (row.content or "").strip() or (row.scene == "group" and not row.group_id):
            skipped += 1
            continue
        key = group_session_key(row.bot_id, row.group_id, row.user_id) if row.scene == "group" else private_session_key(row.bot_id, row.user_id)
        data = grouped.setdefault(key, {"row": row, "rounds": [], "after_clear": False})
        if row.direction == "in" and row.content.strip().startswith(CMD_CLEAR_CONTEXT):
            skipped += len(data["rounds"]) + 1
            data["rounds"] = []
            data["after_clear"] = True
            continue
        if data["after_clear"] and row.direction == "out":
            skipped += 1
            continue
        data["after_clear"] = False
        data["rounds"].append({
            "role": "user" if row.direction == "in" else "assistant",
            "content": row.content, "ts": row.created_at.isoformat(),
        })

    report = {"restored": 0, "messages": 0, "existing": 0, "skipped": skipped}
    llm = LLMService(session)
    for key, data in grouped.items():
        if not data["rounds"]:
            continue
        async with context_service.repo.locked(key):
            if await context_service.repo.get(key) is not None:
                report["existing"] += 1
                report["skipped"] += len(data["rounds"])
                continue
            row = data["row"]
            model = await llm.resolve_model(row.bot_id, row.group_id)
            snapshot = {
                "session_key": key, "bot_id": row.bot_id, "scene": row.scene,
                "user_id": row.user_id, "group_id": row.group_id, "frozen": False,
                "rounds": data["rounds"], "created_at": data["rounds"][0]["ts"],
                "updated_at": data["rounds"][-1]["ts"],
                "char_budget": llm.input_char_budget(model),
            }
            await context_service.repo.save(key, snapshot)
            report["restored"] += 1
            report["messages"] += len(data["rounds"])
    return report
