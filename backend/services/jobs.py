"""后台定时任务入口：由 ``main.py`` 启动时注册到 APScheduler。

每个任务独立开启数据库会话，避免长事务与跨请求持有 session。
"""

from __future__ import annotations

from backend.common.logger import get_logger
from backend.core.config_loader import get_config
from backend.core.runtime import get_cache
from backend.database.db import session_scope
from backend.services.account_service import AccountService
from backend.services.proactive_push_service import ProactivePushService
from backend.services.context_service import ContextService
from backend.services.image_service import ImageService
from backend.services.log_service import LogService
from backend.services.memory_service import MemoryService
from backend.services.system_service import SystemService
from backend.services.tts_service import TTSService

logger = get_logger("yuexu.jobs")


async def push_tick_job() -> None:
    """轮询私聊随机惦记，每次最多发送一人。"""
    async with session_scope() as session:
        service = ProactivePushService(session)
        executed = await service.poll()
        if executed:
            logger.info("本轮自动推送执行 %s 个任务", executed)


async def vitality_tick_job() -> None:
    """活力 Agent 轮询：无聊分达标的会话主动搭话。"""
    from backend.services.vitality_service import VitalityService

    if not get_config().get("vitality.enabled", False):
        return
    async with session_scope() as session:
        try:
            sent = await VitalityService(session).tick()
        except Exception:  # noqa: BLE001 - 轮询失败不影响其他任务
            logger.exception("活力 Agent 轮询异常")
            return
        if sent:
            logger.info("活力 Agent 本轮主动搭话 %s 个会话", sent)


async def context_cleanup_job() -> None:
    """清理过期 / 无内容的上下文会话。"""
    removed = await ContextService().cleanup_expired()
    if removed:
        logger.info("上下文清理完成：%s 个", removed)


async def memory_recovery_job() -> None:
    """补提取已落盘但因排队或重启尚未完成的用户记忆。"""
    from backend.services.memory_recovery import recover_memories

    if not get_config().get("memory.enabled", True):
        return
    async with session_scope() as session:
        report = await recover_memories(session, limit=10)
        if report["processed"] or report["errors"]:
            logger.info("记忆补提取完成：%s", report)


async def voice_cache_cleanup_job() -> None:
    """清理过期语音与生成图片缓存。"""
    await TTSService().cleanup_cache()
    await ImageService().cleanup_cache()


async def log_cleanup_job() -> None:
    """按保留天数清理历史日志。"""
    async with session_scope() as session:
        await LogService(session).cleanup(
            int(get_config().get("scheduler.log_retention_days", 30))
        )


async def backup_job() -> None:
    """定时备份数据库。"""
    async with session_scope() as session:
        await SystemService(session).backup_database()


async def account_reconnect_job() -> None:
    """巡检自动重连账号。"""
    async with session_scope() as session:
        reconnected = await AccountService(session).reconnect_pending()
        if reconnected:
            logger.info("账号自动重连成功 %s 个", reconnected)


# ---------------------------------------------------------------------------
# 记忆库定时维护（4.5.10）
# ---------------------------------------------------------------------------
async def _acquire_job_lock(name: str, ttl: int = 3600) -> bool:
    """互斥锁，防止同一维护任务重复堆积执行。"""
    try:
        return await get_cache().incr(f"joblock:{name}", ttl=ttl) == 1
    except Exception:  # noqa: BLE001 - 缓存异常时允许执行
        logger.warning("获取任务锁失败：%s", name, exc_info=True)
        return True


async def memory_decay_job() -> None:
    """每日热度衰减。"""
    if not await _acquire_job_lock("memory_decay"):
        return
    async with session_scope() as session:
        await MemoryService(session).decay_all()


async def memory_maintenance_job() -> None:
    """每 3 天：自动去重 + 冷记忆淘汰。"""
    if not await _acquire_job_lock("memory_maintenance", ttl=7200):
        return
    async with session_scope() as session:
        service = MemoryService(session)
        removed = await service.dedupe_all()
        purged = await service.purge_cold()
        if removed or purged:
            logger.info("记忆维护完成：去重 %s 条，冷记忆清理 %s 条", removed, purged)


async def memory_gc_job() -> None:
    """每周：向量库 GC。"""
    if not await _acquire_job_lock("memory_gc", ttl=7200):
        return
    async with session_scope() as session:
        await MemoryService(session).gc_vectors()
