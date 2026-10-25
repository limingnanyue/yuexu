"""轻量级结构迁移：自动补齐新增列 + 索引 + 回填历史记忆数据。

脚手架阶段未引入 Alembic，使用 ``ALTER TABLE ADD COLUMN`` 做向前兼容；
新增列统一按可空列添加，再由 ORM 默认值 / 回填 SQL 填充，避免 SQLite
「Cannot add a NOT NULL column with default value NULL」问题。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import case, exists, func, insert, inspect, literal, or_, select, update
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from backend.common.logger import get_logger
from backend.database.models import Base, BotAccount, Character, MemoryEntry, MemoryLibrary

logger = get_logger("yuexu.migrate")

# 旧库补建索引清单（新库 create_all 时已随模型创建）
_PATCH_INDEXES = (
    'CREATE INDEX IF NOT EXISTS ix_memory_target '
    "ON memory_entries (bot_id, target_type, target_id)",
    "CREATE INDEX IF NOT EXISTS ix_memory_entries_rejected "
    "ON memory_entries (rejected)",
    ("CREATE INDEX IF NOT EXISTS ix_memory_hot "
     "ON memory_entries (hot_score)"),
    ("CREATE INDEX IF NOT EXISTS ix_memory_created "
     "ON memory_entries (created_at, id)"),
    "CREATE INDEX IF NOT EXISTS ix_ai_request_logs_user "
    "ON ai_request_logs (user_id)",
    "CREATE INDEX IF NOT EXISTS ix_ai_request_logs_group "
    "ON ai_request_logs (group_id)",
    "CREATE INDEX IF NOT EXISTS ix_message_logs_bot_time "
    "ON message_logs (bot_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_ai_request_logs_bot_time "
    "ON ai_request_logs (bot_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_search_logs_bot_time "
    "ON search_logs (bot_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_push_logs_bot_time "
    "ON push_logs (bot_id, created_at)",
)


async def ensure_schema_compat(engine: AsyncEngine) -> list[str]:
    """补齐模型新增字段，返回新增列列表。"""
    added: list[str] = []

    async with engine.begin() as connection:
        missing = await connection.run_sync(_missing_columns)
        for table_name, column in missing:
            type_sql = column.type.compile(dialect=engine.dialect)
            await connection.exec_driver_sql(
                f'ALTER TABLE "{table_name}" ADD COLUMN "{column.name}" {type_sql}'
            )
            added.append(f"{table_name}.{column.name}")

        if added:
            logger.warning("检测到数据库结构变更，已新增列：%s", ", ".join(added))
        # 仅在确实存在待回填行时才执行全表 UPDATE（避免每次启动空扫）
        await backfill_memory_entries(connection)
        await backfill_memory_libraries(connection)

        await connection.execute(
            update(Character).where(Character.style_settings.is_(None)).values(style_settings={})
        )

        for index_sql in _PATCH_INDEXES:
            try:
                await connection.exec_driver_sql(index_sql)
            except Exception:  # noqa: BLE001 - 索引已存在或数据库不支持时忽略
                logger.debug("索引创建跳过：%s", index_sql)

    return added


async def backfill_memory_libraries(connection: AsyncConnection | AsyncSession) -> None:
    """保留历史分区 ID，补齐账号和已删除连接遗留的记忆库目录。"""
    columns = ["id", "name", "platform", "created_at", "updated_at"]
    moment = datetime.now()
    await connection.execute(
        insert(MemoryLibrary).from_select(columns, select(
            BotAccount.id, BotAccount.name, BotAccount.platform,
            literal(moment), literal(moment),
        ).where(~exists(select(MemoryLibrary.id).where(MemoryLibrary.id == BotAccount.id))))
    )
    await connection.execute(
        insert(MemoryLibrary).from_select(columns, select(
            MemoryEntry.bot_id, literal("已保留记忆库 ") + MemoryEntry.bot_id,
            literal(""), literal(moment), literal(moment),
        ).where(
            MemoryEntry.bot_id != "",
            ~exists(select(MemoryLibrary.id).where(MemoryLibrary.id == MemoryEntry.bot_id)),
        ).distinct())
    )


def _missing_columns(sync_connection) -> list[tuple[str, object]]:
    inspector = inspect(sync_connection)
    tables = set(inspector.get_table_names())
    missing: list[tuple[str, object]] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        existing = {column["name"] for column in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in existing:
                missing.append((table.name, column))
    return missing


def _missing_backfill_conditions():
    return or_(
        MemoryEntry.target_id.is_(None),
        MemoryEntry.target_id == "",
        MemoryEntry.target_type.is_(None),
        MemoryEntry.memory_type.is_(None),
        MemoryEntry.hot_score.is_(None),
    )


async def backfill_memory_entries(connection: Connection) -> int:
    """把旧版本记忆补齐为新的隔离 / 冷热 / 置信字段（无待回填行时直接跳过）。"""
    probe = await connection.execute(
        select(func.count())
        .select_from(MemoryEntry)
        .where(_missing_backfill_conditions())
        .limit(1)
    )
    if int(probe.scalar() or 0) <= 0:
        return 0
    conditions = [_missing_backfill_conditions()]
    statement = (
        update(MemoryEntry)
        .where(*conditions)
        .values(
            target_type=case(
                (MemoryEntry.scope_type == "group", "group"), else_="user"
            ),
            target_id=func.coalesce(
                case(
                    (MemoryEntry.scope_type == "group", MemoryEntry.group_id),
                    else_=MemoryEntry.user_id,
                ),
                MemoryEntry.user_id,
                "",
            ),
            memory_type=case(
                (MemoryEntry.category == "preference", "preference"),
                (MemoryEntry.category == "plan", "plan"),
                else_="fact",
            ),
            hot_score=5.0,
            confidence=0.7,
            fuzzy_weight=0.0,
            rejected=False,
            hit_count=0,
            tag_keywords=[],
        )
        .execution_options(synchronize_session=False)
    )
    result = await connection.execute(statement)
    count = int(result.rowcount or 0)
    if count:
        logger.info("已回填历史记忆字段：%s 条", count)
    return count
