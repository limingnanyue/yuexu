"""受管账号的准备任务；下载期间不占用请求或数据库会话。"""

from __future__ import annotations

import asyncio

from backend.common.constants import Platform
from backend.common.exceptions import AppError
from backend.common.logger import get_logger
from backend.core.background import spawn
from backend.core.runtime import get_runtime
from backend.database.db import session_scope
from backend.repositories.account_repo import AccountRepo
from backend.services.napcat_runtime import napcat_runtime

logger = get_logger("yuexu.account.setup")
_tasks: dict[str, asyncio.Task] = {}
_states: dict[str, dict] = {}
_stopping: dict[str, int] = {}


def is_managed(account) -> bool:
    return account.platform == Platform.QQ.value and (account.adapter_config or {}).get("managed") is True


def get_status(account_id: str) -> dict:
    if account_id in _stopping:
        return {"account_id": account_id, "status": "preparing", "stage": "stopping", "message": "正在停止登录服务，请稍候"}
    if _states.get(account_id, {}).get("status") == "ready" and not napcat_runtime.is_running(account_id):
        _states.pop(account_id, None)
    return {"account_id": account_id, **_states.get(account_id, {
        "status": "idle", "stage": "checking", "message": "点击开始自动准备登录环境",
    })}


def start_prepare(account_id: str) -> dict:
    status = get_status(account_id)
    if account_id in _stopping or status["status"] == "ready":
        return status
    task = _tasks.get(account_id)
    if task is None or task.done():
        _states[account_id] = {"status": "preparing", "stage": "checking", "message": "正在检查登录环境"}
        _tasks[account_id] = spawn(
            _prepare_account(account_id),
            name=f"account-prepare-{account_id}",
            critical=True,
        )
    return get_status(account_id)


async def _prepare_account(account_id: str) -> None:
    def report(stage: str, message: str):
        _states[account_id] = {"status": "preparing", "stage": stage, "message": message}

    try:
        async with session_scope() as session:
            account = await AccountRepo(session).get(account_id)
            if account is None or not is_managed(account):
                _states.pop(account_id, None)
                return
            account_no = account.account_no
        credentials = await napcat_runtime.ensure(account_id, report=report, account_no=account_no)
        async with session_scope() as session:
            repo = AccountRepo(session)
            account = await repo.get(account_id)
            if account is None or not is_managed(account):
                await napcat_runtime.stop(account_id)
                _states.pop(account_id, None)
                return
            credentials["adapter_config"] = {**(account.adapter_config or {}), **credentials["adapter_config"]}
            await repo.update(account, **credentials, last_error=None)
        runtime = get_runtime()
        await runtime.adapter_factory.reset(account_id)
        runtime.state_manager.mark_offline(account_id)
        _states[account_id] = {"status": "ready", "stage": "ready", "message": "登录环境已就绪，正在获取二维码"}
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        message = exc.message if isinstance(exc, AppError) else "登录环境准备失败，请重试；详情见服务日志"
        _states[account_id] = {"status": "error", "stage": "error", "message": message}
        try:
            await napcat_runtime.stop(account_id)
        except Exception:
            logger.warning("停止未就绪的登录环境失败，请检查运行服务：%s", account_id)
        async with session_scope() as session:
            repo = AccountRepo(session)
            account = await repo.get(account_id)
            if account is not None:
                await repo.update(account, last_error=message[:500])
        get_runtime().state_manager.mark_error(account_id, message)
        logger.warning("账号登录环境准备失败：%s (%s)", account_id, type(exc).__name__, exc_info=not isinstance(exc, AppError))


async def cancel_prepare(account_id: str) -> None:
    _stopping[account_id] = _stopping.get(account_id, 0) + 1
    try:
        task = _tasks.get(account_id)
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await napcat_runtime.stop(account_id)
        _tasks.pop(account_id, None)
        _states.pop(account_id, None)
    finally:
        if _stopping[account_id] == 1:
            _stopping.pop(account_id)
        else:
            _stopping[account_id] -= 1


async def close_preparations() -> None:
    tasks = list(_tasks.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    await napcat_runtime.close()
    _tasks.clear()
    _states.clear()
    _stopping.clear()
