"""《月叙》后端入口：只做应用装配、路由注册、生命周期管理，不含业务逻辑。"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.common.cache import init_cache
from backend.common.exceptions import NotFoundError, register_exception_handlers
from backend.common.logger import get_logger, setup_logging
from backend.common.utils import ensure_dir
from backend.core.background import drain_background_tasks
from backend.core.config_loader import get_config
from backend.core.runtime import get_runtime, init_runtime
from backend.database.db import dispose_engine, init_db, session_scope
from backend.database.seed import seed_initial_data
from backend.routers import api_router
from backend.services.account_service import AccountService
from backend.services.auto_push_service import AutoPushService
from backend.repositories.user_push_repo import UserPushRepo
from backend.services.jobs import (
    account_reconnect_job,
    backup_job,
    context_cleanup_job,
    log_cleanup_job,
    memory_decay_job,
    memory_gc_job,
    memory_maintenance_job,
    memory_recovery_job,
    push_tick_job,
    vitality_tick_job,
    voice_cache_cleanup_job,
)

logger = get_logger("yuexu.main")


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------
def _prepare_directories(config) -> None:  # noqa: ANN001
    for key, default in (
        ("paths.static_dir", "static"),
        ("paths.data_dir", "data"),
        ("paths.log_dir", "logs"),
    ):
        ensure_dir(config.resolve_path(str(config.get(key, default))))
    static_dir = config.resolve_path(str(config.get("paths.static_dir", "static")))
    for sub in ("voice_cache", "qrcode_temp", "emoji_lib"):
        ensure_dir(static_dir / sub)
    ensure_dir(config.resolve_path(str(config.get("scheduler.backup_dir", "data/backups"))))


def _register_jobs(scheduler, config) -> None:  # noqa: ANN001
    """注册内置定时任务。"""
    scheduler.add_interval("push_tick", push_tick_job, 60)
    scheduler.add_interval(
        "vitality_tick",
        vitality_tick_job,
        max(30, int(config.get("vitality.interval", 60))),
    )
    scheduler.add_interval(
        "context_cleanup",
        context_cleanup_job,
        int(config.get("scheduler.context_cleanup_interval", 300)),
    )
    scheduler.add_interval("memory_recovery", memory_recovery_job, 300)
    scheduler.add_interval(
        "voice_cleanup",
        voice_cache_cleanup_job,
        int(config.get("scheduler.voice_cleanup_interval", 3600)),
    )
    scheduler.add_interval(
        "account_reconnect",
        account_reconnect_job,
        int(config.get("adapters.reconnect_interval", 15)),
    )
    scheduler.add_cron("log_cleanup", log_cleanup_job, "30 4 * * *")
    # 记忆库维护：每日衰减、每 3 天去重清理、每周向量 GC（错峰执行）
    scheduler.add_cron("memory_decay", memory_decay_job, "10 4 * * *")
    scheduler.add_cron("memory_maintenance", memory_maintenance_job, "20 4 */3 * *")
    scheduler.add_cron("memory_gc", memory_gc_job, "0 5 * * 0")

    backup_hours = int(config.get("scheduler.backup_interval_hours", 24))
    if backup_hours > 0:
        scheduler.add_interval("auto_backup", backup_job, backup_hours * 3600)



async def _ensure_vector_index(config) -> None:  # noqa: ANN001
    """embedding 签名变化时后台重建向量索引（新旧向量空间不可混用）。"""
    if not config.get("memory.enabled", True):
        return
    try:
        from backend.core.background import spawn
        from backend.repositories.memory_repo import MemoryRepo
        from backend.repositories.vector_store import create_vector_store
        from backend.services.memory_maintenance import rebuild_index

        async with session_scope() as session:
            store = create_vector_store(config, MemoryRepo(session))
        if not getattr(store, "needs_reindex", False):
            return

        async def _rebuild() -> None:
            async with session_scope() as session:
                count = await rebuild_index(MemoryRepo(session), store)
            logger.warning("embedding 签名变化，向量索引已重建：%s 条", count)

        logger.warning("检测到向量库 embedding 签名变化，后台重建索引中（期间记忆检索可能降级）")
        spawn(_rebuild(), name="yuexu-vector-reindex")
    except Exception:  # noqa: BLE001 - 签名检查失败不影响启动
        logger.exception("向量索引签名检查失败")


async def _prewarm_vector_index(config) -> None:  # noqa: ANN001
    """启动后台预热内置向量索引：首条消息不再承担全量加载延迟。

    内置引擎为惰性加载，重启后第一条消息若命中冷启动会整段加载记忆并极易
    超过精准检索超时（默认 400ms），触发降级与熔断计数；预热彻底消除该窗口。
    """
    if not config.get("memory.enabled", True):
        return
    if str(config.get("memory.backend", "builtin")).lower() != "builtin":
        return  # chroma 持久化索引随库加载，keyword 无索引可预热
    try:
        from backend.core.background import spawn
        from backend.repositories.memory_repo import MemoryRepo
        from backend.repositories.vector_store import create_vector_store

        async def _warm() -> None:
            async with session_scope() as session:
                store = create_vector_store(config, MemoryRepo(session))
                total = await store.prewarm()
            logger.info("记忆向量索引预热完成：%s 条", total)

        spawn(_warm(), name="yuexu-vector-prewarm")
    except Exception:  # noqa: BLE001 - 预热失败不影响启动
        logger.exception("记忆向量索引预热失败")


async def _startup() -> None:
    config = get_config()
    _prepare_directories(config)

    cache = await init_cache(
        enabled=bool(config.get("redis.enabled", False)),
        url=str(config.get("redis.url", "redis://127.0.0.1:6379/0")),
        prefix=str(config.get("redis.key_prefix", "yuexu:")),
    )
    runtime = init_runtime(cache=cache)

    await init_db(
        str(config.get("database.url", "sqlite+aiosqlite:///./data/yuexu.db")),
        echo=bool(config.get("database.echo", False)),
    )

    async with session_scope() as session:
        created = await seed_initial_data(session)
        if created:
            logger.info("初始化数据：%s", created)
        await AccountService(session).bootstrap()
        await AutoPushService(session).bootstrap()
        await UserPushRepo(session).bootstrap()

    await _ensure_vector_index(config)
    await _prewarm_vector_index(config)

    scheduler = runtime.scheduler
    scheduler.start()
    _register_jobs(scheduler, config)
    logger.info(
        "%s 后端已启动：http://%s:%s（缓存：%s）",
        config.get("app.name", "月叙"),
        config.get("app.host", "127.0.0.1"),
        config.get("app.port", 8000),
        cache.name,
    )


async def _shutdown() -> None:
    runtime = get_runtime()
    runtime.scheduler.shutdown(wait=False)
    from backend.services.account_setup_service import close_preparations
    await close_preparations()
    try:
        await drain_background_tasks(timeout=8)
    except Exception:  # noqa: BLE001
        logger.exception("等待后台任务收尾失败")
    try:
        await runtime.adapter_factory.close_all()
    except Exception:  # noqa: BLE001
        logger.exception("关闭适配器失败")
    if runtime.cache is not None:
        try:
            await runtime.cache.close()
        except Exception:  # noqa: BLE001
            logger.exception("关闭缓存失败")
    from backend.services.llm_service import close_llm_clients
    await close_llm_clients()
    await dispose_engine()
    logger.info("月叙后端已停止")


# ---------------------------------------------------------------------------
# 应用装配
# ---------------------------------------------------------------------------
def create_app() -> FastAPI:
    config = get_config()
    setup_logging(
        log_dir=config.resolve_path(str(config.get("paths.log_dir", "logs"))),
        level="DEBUG" if config.get("app.debug") else "INFO",
        debug=bool(config.get("app.debug", False)),
    )
    _prepare_directories(config)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await _startup()
        try:
            yield
        finally:
            await _shutdown()

    app = FastAPI(
        title=f"{config.get('app.name', '月叙')} API",
        description="AI 多端智能对话机器人管理接口（QQ / 微信 · OneBot11）",
        version=str(config.get("app.version", "0.1.0")),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    register_exception_handlers(app)

    cors_origins = config.get("app.cors_origins", ["*"]) or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in cors_origins],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router)

    static_dir = config.resolve_path(str(config.get("paths.static_dir", "static")))
    ensure_dir(static_dir)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    frontend_dist = config.resolve_path(str(config.get("paths.frontend_dist", "frontend/dist")))

    @app.get("/", include_in_schema=False)
    async def root():
        index_file = frontend_dist / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return {
            "name": config.get("app.name", "月叙"),
            "version": config.get("app.version", "0.1.0"),
            "docs": "/docs",
            "health": "/api/system/health",
        }

    # 前端打包产物托管（Windows 一键包场景），放在最后作为 SPA 兜底
    if frontend_dist.exists():
        assets_dir = frontend_dist / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa_fallback(full_path: str):
            if full_path.startswith(("api", "static", "assets")):
                raise NotFoundError("接口不存在")
            index_file = frontend_dist / "index.html"
            if not index_file.exists():
                raise NotFoundError("前端尚未构建")
            return FileResponse(index_file)

        logger.info("已托管前端静态资源：%s", frontend_dist)

    return app


app = create_app()
