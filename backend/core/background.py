"""轻量后台任务：记忆写入 / 上下文追加等不阻塞回复的异步任务。

背压设计（对应 dispatch.queue_size 配置）：
- 固定 worker 池消费有界队列，突发流量下并发可控（每个 worker 串行执行）；
- 队列满时：``critical=True`` 的任务（如上下文写入）退回独立任务保证执行，
  非关键任务（如记忆抽取）直接丢弃并告警，回复链路不受影响；
- 应用关闭时可 ``drain`` 等待收尾；测试中可显式 ``drain_background_tasks``。
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable

from backend.common.logger import get_logger

logger = get_logger("yuexu.background")

_pending: set[asyncio.Task] = set()
_queue: asyncio.Queue | None = None
_workers: list[asyncio.Task] = []
_dropped = 0


def _pool_settings() -> tuple[int, int]:
    """读取队列容量与 worker 数（配置缺省 200 / 4）。"""
    try:
        from backend.core.config_loader import get_config

        config = get_config()
        return (
            max(1, int(config.get("dispatch.queue_size", 200) or 200)),
            max(1, int(config.get("dispatch.background_workers", 4) or 4)),
        )
    except Exception:  # noqa: BLE001 - 配置不可用时用默认值
        return 200, 4


def _ensure_pool() -> asyncio.Queue | None:
    global _queue
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return None
    if _queue is None:
        capacity, worker_count = _pool_settings()
        _queue = asyncio.Queue(maxsize=capacity)
        for index in range(worker_count):
            worker = asyncio.create_task(_worker_loop(), name=f"yuexu-bg-worker-{index}")
            _workers.append(worker)
        logger.info(
            "后台任务池已启动：workers=%s queue=%s", worker_count, capacity
        )
    return _queue


async def _worker_loop() -> None:
    while True:
        coro, name = await _queue.get()
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 后台任务异常不影响池
            logger.error("后台任务异常：%s", name, exc_info=True)
        finally:
            _queue.task_done()


def spawn(
    coro: Awaitable[Any],
    *,
    name: str = "yuexu-bg",
    critical: bool = False,
) -> asyncio.Task | None:
    """提交后台任务并跟踪；不在事件循环中时返回 None。

    - ``critical=True``：直接创建独立任务（句柄可 ``cancel`` / ``done``，
      供账号登录准备等需要生命周期控制的调用方使用）；
    - 默认（非关键）：进入有界队列由 worker 池消费；队列满时丢弃并告警
      （记忆抽取等可容忍丢失的任务）。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("当前无事件循环，后台任务降级为同步执行：%s", name)
        try:
            coro.close()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        return None
    if critical:
        task = asyncio.create_task(coro, name=name)  # type: ignore[arg-type]
        _pending.add(task)
        task.add_done_callback(_on_done)
        return task
    queue = _ensure_pool()
    if queue is None:
        return None
    try:
        queue.put_nowait((coro, name))
        return None
    except asyncio.QueueFull:
        global _dropped
        _dropped += 1
        try:
            coro.close()  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "后台任务队列已满，丢弃非关键任务：%s（累计丢弃 %s）", name, _dropped
        )
        return None


def _on_done(task: asyncio.Task) -> None:
    _pending.discard(task)
    if task.cancelled():
        return
    try:
        error = task.exception()
    except asyncio.CancelledError:
        return
    if error is not None:
        logger.error("后台任务异常：%s", task.get_name(), exc_info=error)


async def drain_background_tasks(timeout: float = 10.0) -> int:
    """等待后台任务完成（超时后取消），返回完成数量。

    排空后销毁 worker 池；后续再次 ``spawn`` 时按需重建（主要服务测试与关停）。
    """
    done_count = 0
    queue = _queue
    if queue is not None:
        try:
            await asyncio.wait_for(queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("后台任务队列排空超时（%.0fs），取消剩余任务", timeout)
        # 取消 worker，丢弃尚未执行的排队任务（未启动的协程直接关闭）
        for worker in _workers:
            worker.cancel()
        await asyncio.gather(*_workers, return_exceptions=True)
        _workers.clear()
        while not queue.empty():
            coro, _name = queue.get_nowait()
            coro.close()
            queue.task_done()
        _reset_pool()
        done_count += 1

    tasks = list(_pending)
    if tasks:
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        done_count += len(done)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    return done_count


def _reset_pool() -> None:
    global _queue
    _queue = None


def pending_background_tasks() -> int:
    queued = _queue.qsize() if _queue is not None else 0
    return len(_pending) + queued
