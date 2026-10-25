"""数据库引擎与会话管理（SQLite 本地 / PostgreSQL 服务端）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from sqlalchemy import event, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.common.logger import get_logger
from backend.database.models import Base

logger = get_logger("yuexu.db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _prepare_sqlite_dir(url: str) -> None:
    """SQLite 文件所在目录不存在时自动创建。"""
    try:
        database = make_url(url).database
    except Exception:  # noqa: BLE001
        return
    if database and database != ":memory:":
        Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def create_engine(url: str, echo: bool = False) -> AsyncEngine:
    """按连接串创建异步引擎。"""
    _prepare_sqlite_dir(url)
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["timeout"] = 30

    engine = create_async_engine(
        url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )

    if url.startswith("sqlite"):
        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            # 读性能调优：临时表走内存、扩大页缓存、mmap 映射数据文件，
            # 记忆/日志表扫描不再受进程页缓存抖动影响
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA cache_size=-32768")
            cursor.execute("PRAGMA mmap_size=268435456")
            cursor.execute("PRAGMA optimize")
            cursor.close()

    return engine


def init_engine(url: str, echo: bool = False) -> AsyncEngine:
    """初始化全局引擎与会话工厂（幂等）。"""
    global _engine, _session_factory
    if _engine is not None:
        return _engine
    _engine = create_engine(url, echo=echo)
    _session_factory = async_sessionmaker(
        _engine, class_=AsyncSession, expire_on_commit=False
    )
    logger.info("数据库引擎已初始化：%s", url)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        raise RuntimeError("数据库尚未初始化，请先调用 init_engine()")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("数据库尚未初始化，请先调用 init_engine()")
    return _session_factory


async def init_models() -> None:
    """建表 + 向前兼容补列（脚手架阶段使用 create_all，后续可切换 Alembic）。"""
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    from backend.database.migrate import ensure_schema_compat

    await ensure_schema_compat(engine)
    logger.info("数据表检查 / 创建完成")


async def init_db(url: str, echo: bool = False) -> None:
    init_engine(url, echo=echo)
    await init_models()


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """非 HTTP 场景（定时任务、消息分发）使用的会话上下文。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("数据库连接已释放")
    _engine = None
    _session_factory = None


async def check_database() -> bool:
    """健康检查：执行一次最简单的查询。"""
    try:
        engine = get_engine()
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        logger.exception("数据库健康检查失败")
        return False
