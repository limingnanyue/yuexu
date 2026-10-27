"""缓存抽象层：Redis 优先，异常 / 未启用时自动降级为进程内缓存。

- 启动时 Redis 不可用 → 直接使用内存缓存；
- 运行中 Redis 连接异常 → ``FailoverCache`` 自动切换内存缓存并后台探测重连，
  恢复后自动切回（文档 10.8：会话缓存异常不阻断对话）；
- ``incr`` 使用 Lua 脚本保证 INCR + EXPIRE 原子性，避免计数器永不过期。
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger("yuexu.cache")


class CacheBackend(ABC):
    """缓存后端抽象接口。"""

    name: str = "base"

    def __init__(self, prefix: str = "") -> None:
        self.prefix = prefix or ""

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    # -- 基础 KV ---------------------------------------------------------
    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl: int | None = None) -> None: ...

    @abstractmethod
    async def delete(self, *keys: str) -> None: ...

    @abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abstractmethod
    async def incr(self, key: str, ttl: int | None = None) -> int: ...

    @abstractmethod
    async def keys(self, pattern: str = "*") -> list[str]: ...

    @abstractmethod
    async def ttl(self, key: str) -> int: ...

    @abstractmethod
    async def close(self) -> None: ...

    # -- 批量便捷方法（Redis 实现用 pipeline，默认逐个执行） ---------------
    async def get_many(self, keys: list[str]) -> list[str | None]:
        if not keys:
            return []
        return [await self.get(key) for key in keys]

    async def ttl_many(self, keys: list[str]) -> list[int]:
        if not keys:
            return []
        return [await self.ttl(key) for key in keys]

    # -- JSON 便捷方法 ---------------------------------------------------
    async def get_json(self, key: str, default: Any = None) -> Any:
        raw = await self.get(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("缓存值不是合法 JSON，key=%s", key)
            return default

    async def set_json(self, key: str, value: Any, ttl: int | None = None) -> None:
        await self.set(key, json.dumps(value, ensure_ascii=False), ttl=ttl)


class MemoryCache(CacheBackend):
    """进程内 TTL 缓存，用于无 Redis 的本地调试 / 单机部署场景。

    性能约束（旧实现的问题）：每次 ``get`` / ``incr`` / ``keys`` 都会遍历整张
    ``_store`` 做过期清理，单次读取因此变成 O(条目数)。本项目的默认部署没有
    Redis，缓存里同时挂着记忆召回结果、质量反馈标记、摘要退避标记等，条目数
    随会话量线性增长——命中率越高，扫描次数越多，整体退化为 O(n²)。

    现在改为三级惰性策略，语义保持不变：

    1. **单键就地过期**：读取某个 key 时只看它自己的 deadline，命中 O(1)；
    2. **阈值批量清理**：累计操作数或距上次清理时间超过阈值才全表扫一次，
       把清理成本摊到批量操作上；
    3. **容量上限**：条目数超过 ``_MAX_ENTRIES`` 时按插入顺序淘汰最旧条目，
       避免长时间运行后内存只增不减（缓存允许丢失，丢失后会重新计算）。
    """

    name = "memory"

    # 批量清理阈值：累计 256 次操作或 1 秒后触发一次全表过期清理。
    _PURGE_OPERATIONS = 256
    _PURGE_INTERVAL_SECONDS = 1.0
    # 条目上限：缓存允许丢失，超过上限后淘汰最旧条目。
    _MAX_ENTRIES = 20000

    def __init__(self, prefix: str = "", *, max_entries: int = 20000) -> None:
        super().__init__(prefix)
        self._store: dict[str, tuple[str, float | None]] = {}
        self._max_entries = max(1, int(max_entries))
        self._operations = 0
        self._last_purge = time.time()

    def _live(self, full_key: str) -> tuple[str, float | None] | None:
        """读取单个键并就地处理过期（O(1)，不触发全表扫描）。"""
        item = self._store.get(full_key)
        if item is None:
            return None
        value, deadline = item
        if deadline is not None and deadline <= time.time():
            self._store.pop(full_key, None)
            return None
        return value, deadline

    def _trim(self, current: float) -> None:
        """条目超上限时按插入顺序淘汰最旧条目（dict 保序，均摊 O(1)）。"""
        overflow = len(self._store) - self._max_entries
        if overflow <= 0:
            return
        for key in list(self._store.keys())[:overflow]:
            self._store.pop(key, None)

    def _purge(self, *, force: bool = False) -> None:
        """按阈值惰性清理过期条目（``force`` 供 ``keys`` 等全量操作用）。"""
        self._operations += 1
        current = time.time()
        if (
            not force
            and self._operations < self._PURGE_OPERATIONS
            and current - self._last_purge < self._PURGE_INTERVAL_SECONDS
        ):
            return
        self._operations = 0
        self._last_purge = current
        expired = [
            key for key, (_, deadline) in self._store.items()
            if deadline is not None and deadline <= current
        ]
        for key in expired:
            self._store.pop(key, None)
        self._trim(current)

    async def get(self, key: str) -> str | None:
        self._purge()
        item = self._live(self._key(key))
        return item[0] if item else None

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        self._purge()
        deadline = time.time() + ttl if ttl and ttl > 0 else None
        self._store[self._key(key)] = (value, deadline)
        if len(self._store) > self._max_entries:
            self._trim(time.time())

    async def delete(self, *keys: str) -> None:
        for key in keys:
            self._store.pop(self._key(key), None)

    async def exists(self, key: str) -> bool:
        return await self.get(key) is not None

    async def incr(self, key: str, ttl: int | None = None) -> int:
        self._purge()
        full_key = self._key(key)
        item = self._live(full_key)
        raw, deadline = item or (None, None)
        value = int(raw or 0) + 1
        # 与 Redis Lua 脚本一致：只在计数器首次创建时设置过期时间。
        if deadline is None and ttl and ttl > 0:
            deadline = time.time() + ttl
        self._store[full_key] = (str(value), deadline)
        if len(self._store) > self._max_entries:
            self._trim(time.time())
        return value

    async def keys(self, pattern: str = "*") -> list[str]:
        # keys 本身就要遍历全表，这里顺便强制清理一次，返回值不含过期条目。
        self._purge(force=True)
        full_pattern = self._key(pattern)
        return [
            key[len(self.prefix):] for key in self._store
            if fnmatch.fnmatch(key, full_pattern)
        ]

    async def ttl(self, key: str) -> int:
        item = self._live(self._key(key))
        if not item or item[1] is None:
            return -1
        return max(int(item[1] - time.time()), 0)

    async def close(self) -> None:
        self._store.clear()


class RedisCache(CacheBackend):
    """Redis 异步缓存实现。"""

    name = "redis"

    # Lua：INCR 与首次 EXPIRE 原子执行，杜绝两步竞态导致的永不过期计数器
    _INCR_LUA = (
        "local v = redis.call('INCR', KEYS[1]) "
        "if v == 1 and ARGV[1] ~= '' then redis.call('EXPIRE', KEYS[1], ARGV[1]) end "
        "return v"
    )

    def __init__(self, url: str, prefix: str = "") -> None:
        super().__init__(prefix)
        import redis.asyncio as redis  # 延迟导入，便于无 Redis 环境运行

        self._client = redis.from_url(
            url,
            decode_responses=True,
            max_connections=50,
            socket_timeout=5,
            socket_connect_timeout=3,
            health_check_interval=30,
            retry_on_timeout=True,
        )

    async def ping(self) -> bool:
        return bool(await self._client.ping())

    async def get(self, key: str) -> str | None:
        return await self._client.get(self._key(key))

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        if ttl and ttl > 0:
            await self._client.set(self._key(key), value, ex=ttl)
        else:
            await self._client.set(self._key(key), value)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._client.delete(*(self._key(key) for key in keys))

    async def exists(self, key: str) -> bool:
        return bool(await self._client.exists(self._key(key)))

    async def incr(self, key: str, ttl: int | None = None) -> int:
        full_key = self._key(key)
        value = await self._client.eval(
            self._INCR_LUA, 1, full_key, str(int(ttl)) if ttl and ttl > 0 else ""
        )
        return int(value)

    async def keys(self, pattern: str = "*") -> list[str]:
        found: list[str] = []
        async for key in self._client.scan_iter(match=self._key(pattern), count=200):
            found.append(key[len(self.prefix):] if self.prefix else key)
        return found

    async def ttl(self, key: str) -> int:
        return int(await self._client.ttl(self._key(key)))

    async def get_many(self, keys: list[str]) -> list[str | None]:
        if not keys:
            return []
        pipe = self._client.pipeline(transaction=False)
        for key in keys:
            pipe.get(self._key(key))
        return list(await pipe.execute())

    async def ttl_many(self, keys: list[str]) -> list[int]:
        if not keys:
            return []
        pipe = self._client.pipeline(transaction=False)
        for key in keys:
            pipe.ttl(self._key(key))
        return [int(value) for value in await pipe.execute()]

    async def close(self) -> None:
        await self._client.aclose()


class FailoverCache(CacheBackend):
    """Redis 主缓存 + 内存兜底：运行中连接故障自动降级、恢复后切回。"""

    name = "redis"

    _DIRECT = {"get", "set", "delete", "exists", "incr", "keys", "ttl", "get_many", "ttl_many"}

    def __init__(
        self, primary: RedisCache, fallback: MemoryCache, probe_interval: float = 10.0
    ) -> None:
        super().__init__(primary.prefix)
        self._primary = primary
        self._fallback = fallback
        self._degraded = False
        self._probe_interval = max(3.0, float(probe_interval))
        self._probe_task: asyncio.Task | None = None

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if not self._degraded:
            try:
                return await getattr(self._primary, method)(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                if not self._is_connection_error(exc):
                    raise
                self._degrade(exc)
        return await getattr(self._fallback, method)(*args, **kwargs)

    @staticmethod
    def _is_connection_error(exc: BaseException) -> bool:
        try:
            import redis.exceptions as redis_exc
        except ImportError:  # pragma: no cover - 无 Redis 环境不会构造本类
            return isinstance(exc, (ConnectionError, OSError))
        return isinstance(
            exc,
            (redis_exc.ConnectionError, redis_exc.TimeoutError, ConnectionError, OSError),
        )

    def _degrade(self, exc: BaseException) -> None:
        self._degraded = True
        logger.warning("Redis 连接异常（%s），缓存已降级为进程内缓存", exc)
        if self._probe_task is None or self._probe_task.done():
            self._probe_task = asyncio.get_running_loop().create_task(
                self._probe_loop(), name="yuexu-cache-reconnect"
            )

    async def _probe_loop(self) -> None:
        while self._degraded:
            await asyncio.sleep(self._probe_interval)
            try:
                if await self._primary.ping():
                    self._degraded = False
                    logger.info("Redis 连接已恢复，缓存切回主实例")
                    return
            except Exception:  # noqa: BLE001 - 继续探测
                continue

    async def ping(self) -> bool:
        if self._degraded:
            return False
        return await self._primary.ping()

    async def get(self, key: str) -> str | None:
        return await self._call("get", key)

    async def set(self, key: str, value: str, ttl: int | None = None) -> None:
        await self._call("set", key, value, ttl=ttl)

    async def delete(self, *keys: str) -> None:
        await self._call("delete", *keys)

    async def exists(self, key: str) -> bool:
        return await self._call("exists", key)

    async def incr(self, key: str, ttl: int | None = None) -> int:
        return await self._call("incr", key, ttl=ttl)

    async def keys(self, pattern: str = "*") -> list[str]:
        return await self._call("keys", pattern)

    async def ttl(self, key: str) -> int:
        return await self._call("ttl", key)

    async def get_many(self, keys: list[str]) -> list[str | None]:
        return await self._call("get_many", keys)

    async def ttl_many(self, keys: list[str]) -> list[int]:
        return await self._call("ttl_many", keys)

    async def close(self) -> None:
        if self._probe_task is not None and not self._probe_task.done():
            self._probe_task.cancel()
            try:
                await self._probe_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self._fallback.close()
        await self._primary.close()


async def init_cache(
    enabled: bool,
    url: str = "redis://127.0.0.1:6379/0",
    prefix: str = "yuexu:",
) -> CacheBackend:
    """创建缓存后端；Redis 不可用时降级为内存缓存（文档 10.8）。"""
    if enabled:
        try:
            primary = RedisCache(url, prefix=prefix)
            await primary.ping()
            logger.info("Redis 连接成功：%s", url)
            return FailoverCache(primary, MemoryCache(prefix=prefix))
        except Exception as exc:  # noqa: BLE001 - 任意连接异常都降级
            logger.warning("Redis 不可用（%s），已降级为内存缓存", exc)
    else:
        logger.info("Redis 未启用，使用内存缓存（会话原文由数据库持久保存）")
    return MemoryCache(prefix=prefix)
