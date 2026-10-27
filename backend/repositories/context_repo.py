"""上下文会话数据访问：数据库保留快照与原文，Redis / 内存仅作缓存。

会话结构::

    {
      "session_key": "ctx:group:{bot}:{group}:{user}",
      "bot_id": "...", "scene": "private", "group_id": null, "user_id": "...",
      "frozen": false,
      "rounds": [{"role": "user", "content": "...", "ts": "..."}],
      "created_at": "...", "updated_at": "..."
    }

并发安全：会话更新是「读 → 改 → 写」三步，同一会话并发追加会互相覆盖丢轮次；
``locked()`` 提供按会话 key 的进程内互斥锁，Service 层的写入路径统一持锁。
（多进程部署场景需扩展为 Redis 分布式锁，单机部署当前实现已足够。）
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from copy import deepcopy
from typing import Any

from sqlalchemy import delete, select, update

from backend.common.cache import CacheBackend
from backend.common.constants import CONTEXT_KEY_PATTERN
from backend.database.models import ContextSession


class KeyedLockPool:
    """按 key 复用 asyncio.Lock；规模超限时清理无人在持的锁。"""

    _PRUNE_SIZE = 4096

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def locked(self, key: str) -> Iterator[None]:
        if len(self._locks) > self._PRUNE_SIZE:
            self._locks = {
                name: lock for name, lock in self._locks.items() if lock.locked()
            }
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()
        async with lock:
            yield


_session_locks = KeyedLockPool()


class ContextRepo:
    """上下文会话缓存仓库。"""

    def __init__(
        self,
        cache: CacheBackend,
        ttl: int = 600,
        max_rounds: int = 20,
        session_factory=None,
    ) -> None:
        self.cache = cache
        self.ttl = max(1, int(ttl))
        self.max_rounds = max(0, int(max_rounds))
        self.session_factory = session_factory

    def locked(self, session_key: str):
        """按会话 key 加锁，防止并发读-改-写丢轮次。"""
        return _session_locks.locked(session_key)

    async def get(self, session_key: str) -> dict[str, Any] | None:
        data = await self.cache.get_json(session_key)
        if isinstance(data, dict) and data:
            return data
        if self.session_factory is not None:
            async with self.session_factory() as database:
                row = await database.get(ContextSession, session_key)
                if row is not None:
                    data = deepcopy(row.snapshot)
                    await self.cache.set_json(session_key, data, ttl=self.ttl)
                    return data
        return None

    async def save(
        self,
        session_key: str,
        data: dict[str, Any],
        *,
        append_messages: list | None = None,
        archive_messages: list | None = None,
    ) -> None:
        """保存会话快照；``archive_messages`` 中的原文追加到归档列。

        写放大修复：旧实现把每条消息都追加进 ``archive`` JSON 列，并且每次保存
        都 ``get`` 整行（``archive`` 一并反序列化）再整体重写。第 N 条消息时
        ``archive`` 已有约 N 条原文，单条消息的写入量因此是 O(历史长度)、累计
        O(历史长度²)，长会话下每条消息都要读写几十 KB~几 MB 的 JSON。

        现在 ``archive`` 的语义是「已经移出工作窗口的原文」：

        - ``archive_messages`` 由压缩流程显式传入（那批真正被裁掉的消息），
          每条消息只会归档一次，单条消息的写入量降到 O(窗口长度)；
          ``get_archive`` 把归档与当前窗口拼接回来，对外「全量原文」视图不变；
        - 没有归档内容时走 Core ``UPDATE`` 只更新快照列，不再把整段 archive
          读进内存；
        - ``append_messages`` 保留给历史调用方（“刚刚追加了这些消息”）：这些
          消息仍在 ``data["rounds"]`` 里，通过快照就能读回，不需要重复归档。
          注意判断「是否仍在窗口内」必须按**对象身份**，不能按
          ``(role, content, ts)`` 比较——同一秒内重复问同一句话会产生完全
          相同的三元组，按内容比较会把已裁掉的消息误判成仍在窗口内而漏归档。
        """
        archived: list = list(archive_messages or [])
        if archive_messages is None and append_messages:
            # 兼容路径：只归档「已经不在快照 rounds 里」的那部分（按身份判定）
            live = {id(item) for item in (data.get("rounds") or [])}
            archived = [item for item in append_messages if id(item) not in live]
        if self.session_factory is not None:
            async with self.session_factory() as database:
                if archived:
                    # 需要追加归档：只有这条路径必须读出 archive 列
                    row = await database.get(ContextSession, session_key)
                    if row is None:
                        database.add(ContextSession(
                            session_key=session_key,
                            snapshot=deepcopy(data),
                            archive=deepcopy(archived),
                        ))
                    else:
                        row.snapshot = deepcopy(data)
                        row.archive = [*(row.archive or []), *deepcopy(archived)]
                else:
                    # 常见路径（每条消息）：只写快照列，不触碰 archive
                    saved = await database.execute(
                        update(ContextSession)
                        .where(ContextSession.session_key == session_key)
                        .values(snapshot=deepcopy(data))
                    )
                    if not saved.rowcount:
                        database.add(ContextSession(
                            session_key=session_key,
                            snapshot=deepcopy(data),
                            archive=[],
                        ))
                await database.commit()
        await self.cache.set_json(session_key, data, ttl=self.ttl)

    async def get_archive(self, session_key: str) -> list:
        """全量原文 = 已归档（离开窗口）的原文 + 当前窗口内的原文。

        两者按时间先后天然有序：归档总是更早的消息，拼接后与旧版「逐条消息
        全部归档」的结果一致，但归档列不再需要随每条消息重写。
        """
        if self.session_factory is not None:
            async with self.session_factory() as database:
                row = (await database.execute(
                    select(ContextSession.archive, ContextSession.snapshot)
                    .where(ContextSession.session_key == session_key)
                )).first()
                if row is None:
                    return []
                archive = deepcopy(row[0] or [])
                rounds = deepcopy((row[1] or {}).get("rounds") or [])
                return [*archive, *rounds]
        return list((await self.get(session_key) or {}).get("rounds") or [])

    async def _get_many(self, keys: list[str]) -> list[dict[str, Any] | None]:
        sessions = []
        for raw in await self.cache.get_many(keys):
            try:
                value = json.loads(raw) if raw is not None else None
            except (TypeError, ValueError):
                value = None
            sessions.append(value if isinstance(value, dict) else None)
        return sessions

    async def delete(self, session_key: str) -> None:
        if self.session_factory is not None:
            async with self.session_factory() as database:
                await database.execute(delete(ContextSession).where(ContextSession.session_key == session_key))
                await database.commit()
        await self.cache.delete(session_key)

    async def touch(self, session_key: str) -> None:
        """仅续期 TTL，不改内容（持锁执行避免回写旧值）。"""
        async with self.locked(session_key):
            data = await self.get(session_key)
            if data is not None:
                await self.save(session_key, data)

    async def list_keys(self) -> list[str]:
        keys = await self.cache.keys(CONTEXT_KEY_PATTERN)
        if self.session_factory is not None:
            async with self.session_factory() as database:
                keys = list(dict.fromkeys([*keys, *(await database.scalars(select(ContextSession.session_key))).all()]))
        # 兼容缓存 key 前缀差异，只保留会话 key
        return [key for key in keys if key.startswith("ctx:")]

    async def list_sessions(self) -> list[dict[str, Any]]:
        """批量读取全部会话（pipeline 一次往返），避免逐 key N+1 网络往返。"""
        if self.session_factory is not None:
            async with self.session_factory() as database:
                rows = (await database.scalars(select(ContextSession))).all()
                persisted = {row.session_key: deepcopy(row.snapshot) for row in rows}
        else:
            persisted = {}
        keys = await self.list_keys()
        if not keys:
            return []
        sessions: list[dict[str, Any]] = []
        batch = 100
        for start in range(0, len(keys), batch):
            chunk = keys[start : start + batch]
            values = await self._get_many(chunk)
            ttls = await self.cache.ttl_many(chunk)
            for key, value, ttl in zip(chunk, values, ttls):
                value = persisted.get(key, value)
                if not isinstance(value, dict) or not value:
                    continue
                value.setdefault("session_key", key)
                value["ttl"] = ttl
                sessions.append(value)
        sessions.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
        return sessions

    async def count(self) -> int:
        return len(await self.list_keys())

    async def clear_all(self) -> int:
        keys = await self.list_keys()
        if self.session_factory is not None:
            async with self.session_factory() as database:
                await database.execute(delete(ContextSession))
                await database.commit()
        if keys:
            await self.cache.delete(*keys)
        return len(keys)

    async def cleanup(self) -> int:
        """清理损坏 / 无内容的会话条目（正常过期由缓存 TTL 自动完成）。"""
        keys = await self.list_keys()
        if not keys:
            return 0
        removed = 0
        batch = 100
        for start in range(0, len(keys), batch):
            chunk = keys[start : start + batch]
            for key in chunk:
                async with self.locked(key):
                    value = await self.get(key)
                    if not value or not (value.get("rounds") or value.get("summary")):
                        await self.delete(key)
                        removed += 1
        return removed
