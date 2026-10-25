"""APScheduler 定时任务管理：自动推送、上下文清理、语音缓存清理、数据备份共用。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.common.logger import get_logger

logger = get_logger("yuexu.scheduler")

JobCallable = Callable[..., Awaitable[Any]]


class SchedulerManager:
    """AsyncIOScheduler 封装，统一任务 ID 与异常日志。"""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(
            job_defaults={
                "coalesce": True,
                "max_instances": 1,
                "misfire_grace_time": 60,
            }
        )

    # ------------------------------------------------------------------
    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("定时任务调度器已启动")

    def shutdown(self, wait: bool = False) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=wait)
            logger.info("定时任务调度器已停止")

    @property
    def running(self) -> bool:
        return bool(self._scheduler.running)

    # ------------------------------------------------------------------
    def add_interval(
        self,
        job_id: str,
        func: JobCallable,
        seconds: int,
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        replace: bool = True,
    ) -> None:
        if seconds <= 0:
            logger.debug("跳过无效间隔任务：%s（%ss）", job_id, seconds)
            return
        self._scheduler.add_job(
            self._wrap(job_id, func),
            IntervalTrigger(seconds=seconds),
            id=job_id,
            args=args,
            kwargs=kwargs or {},
            replace_existing=replace,
        )
        logger.debug("注册间隔任务 %s（每 %ss）", job_id, seconds)

    def add_cron(
        self,
        job_id: str,
        func: JobCallable,
        cron: str,
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        replace: bool = True,
    ) -> None:
        """注册 cron 任务，表达式为 5 段：分 时 日 月 周。"""
        try:
            trigger = CronTrigger.from_crontab(cron)
        except ValueError as exc:
            logger.error("cron 表达式无效 %s：%s", cron, exc)
            raise
        self._scheduler.add_job(
            self._wrap(job_id, func),
            trigger,
            id=job_id,
            args=args,
            kwargs=kwargs or {},
            replace_existing=replace,
        )
        logger.debug("注册 cron 任务 %s（%s）", job_id, cron)

    def add_date(
        self,
        job_id: str,
        func: JobCallable,
        run_date: datetime,
        *,
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        replace: bool = True,
    ) -> None:
        self._scheduler.add_job(
            self._wrap(job_id, func),
            DateTrigger(run_date=run_date),
            id=job_id,
            args=args,
            kwargs=kwargs or {},
            replace_existing=replace,
        )
        logger.debug("注册一次性任务 %s（%s）", job_id, run_date)

    # ------------------------------------------------------------------
    def remove(self, job_id: str) -> None:
        try:
            self._scheduler.remove_job(job_id)
        except Exception:  # noqa: BLE001 - 任务不存在时忽略
            logger.debug("任务不存在，跳过移除：%s", job_id)

    def remove_prefix(self, prefix: str) -> int:
        removed = 0
        for job in self._scheduler.get_jobs():
            if job.id.startswith(prefix):
                self.remove(job.id)
                removed += 1
        return removed

    def get_job(self, job_id: str):
        return self._scheduler.get_job(job_id)

    def next_run_time(self, job_id: str) -> datetime | None:
        job = self.get_job(job_id)
        return job.next_run_time if job else None

    def jobs(self) -> list[dict[str, Any]]:
        """列出全部任务（供系统页展示）。"""
        result = []
        for job in self._scheduler.get_jobs():
            result.append({
                "id": job.id,
                "next_run_time": job.next_run_time.isoformat(timespec="seconds")
                if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return result

    # ------------------------------------------------------------------
    @staticmethod
    def _wrap(job_id: str, func: JobCallable) -> JobCallable:
        """包装任务函数，统一捕获异常，避免单个任务异常导致调度器崩溃。"""

        async def runner(*args: Any, **kwargs: Any) -> None:
            try:
                await func(*args, **kwargs)
            except Exception:  # noqa: BLE001
                logger.exception("定时任务执行失败：%s", job_id)

        return runner
