"""官方渠道的消息接收生命周期与分发；每次分发使用独立数据库会话。"""

import asyncio
import hashlib
from collections import deque

from backend.common.exceptions import AdapterError
from backend.common.constants import Platform
from backend.common.logger import get_logger
from backend.core.runtime import get_cache, get_runtime
from backend.database.db import session_scope
from backend.repositories.account_repo import AccountRepo

logger = get_logger("yuexu.channel")


async def dispatch_channel_payload(adapter, raw):
    from backend.services.bot_dispatch_service import BotDispatchService

    event = adapter.parse_event(raw, adapter.account_id)
    if event is None:
        return
    cache = get_cache()
    event_id = raw.get("id") or event.message_id
    key = "channel:event:" + adapter.account_id + ":" + hashlib.sha256(str(event_id).encode()).hexdigest()
    if event_id and await cache.incr(key, ttl=3600) > 1:
        return
    try:
        async with session_scope() as session:
            await BotDispatchService(session, adapter=adapter).handle_event(event)
    except Exception:
        if event_id:
            await cache.delete(key)
        raise


def start_receiver(adapter):
    if adapter.receive_task is None or adapter.receive_task.done():
        adapter.receive_task = asyncio.create_task(_receive(adapter), name=f"channel-{adapter.account_id}")


async def _receive(adapter):
    state = get_runtime().state_manager
    failures = 0
    pending = deque()
    saved_cursor = adapter.options.config.get("get_updates_buf")
    try:
        while True:
            try:
                if not pending:
                    pending.extend(await adapter.receive_events())
                failures = 0
                if not state.is_online(adapter.account_id):
                    state.mark_online(adapter.account_id)
                state.heartbeat(adapter.account_id)
                while pending:
                    await dispatch_channel_payload(adapter, pending[0])
                    pending.popleft()
                cursor = adapter.options.config.get("get_updates_buf")
                if adapter.platform == Platform.WECHAT_CLAWBOT.value and cursor and cursor != saved_cursor:
                    async with session_scope() as session:
                        repo = AccountRepo(session)
                        account = await repo.get(adapter.account_id)
                        if account is None:
                            return
                        await repo.update(account, adapter_config={**(account.adapter_config or {}), "get_updates_buf": cursor})
                    saved_cursor = cursor
                await asyncio.sleep(1)
            except AdapterError as exc:
                state.mark_error(adapter.account_id, str(exc))
                failures += 1
                if not adapter.options.token or failures >= 10:
                    return
                await asyncio.sleep(min(failures * 2, 30))
            except Exception:
                logger.exception("渠道消息处理失败：%s", adapter.account_id)
                await asyncio.sleep(5)
    except asyncio.CancelledError:
        raise
