"""运行时上下文：保存全局单例依赖（缓存、调度器、账号状态、适配器工厂、钩子）。

HTTP 依赖注入与后台定时任务共用同一份实例，避免出现两套状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from backend.adapters.adapter_factory import AdapterFactory, adapter_factory
from backend.common.cache import CacheBackend, MemoryCache
from backend.core.config_loader import ConfigLoader, get_config
from backend.core.hooks import HookRegistry, hook_registry
from backend.core.scheduler import SchedulerManager
from backend.core.state_manager import AccountStateManager


@dataclass
class RuntimeContext:
    """全局运行时依赖容器。"""

    config: ConfigLoader = field(default_factory=get_config)
    cache: CacheBackend | None = None
    scheduler: SchedulerManager = field(default_factory=SchedulerManager)
    state_manager: AccountStateManager = field(default_factory=AccountStateManager)
    adapter_factory: AdapterFactory = field(default_factory=lambda: adapter_factory)
    hooks: HookRegistry = field(default_factory=lambda: hook_registry)


_runtime = RuntimeContext()


def get_runtime() -> RuntimeContext:
    return _runtime


def init_runtime(
    *,
    cache: CacheBackend | None = None,
    config: ConfigLoader | None = None,
    scheduler: SchedulerManager | None = None,
    state_manager: AccountStateManager | None = None,
    adapter_factory_instance: AdapterFactory | None = None,
) -> RuntimeContext:
    """初始化运行时依赖（应用启动时调用）。"""
    global _runtime
    updates: dict = {}
    if cache is not None:
        updates["cache"] = cache
    if config is not None:
        updates["config"] = config
    if scheduler is not None:
        updates["scheduler"] = scheduler
    if state_manager is not None:
        updates["state_manager"] = state_manager
    if adapter_factory_instance is not None:
        updates["adapter_factory"] = adapter_factory_instance
    if updates:
        _runtime = replace(_runtime, **updates)
    return _runtime


def reset_runtime() -> RuntimeContext:
    """测试用：恢复初始运行时。"""
    global _runtime
    _runtime = RuntimeContext()
    return _runtime


def get_cache() -> CacheBackend:
    """获取缓存；未初始化时回落到内存缓存，保证服务可单独实例化。"""
    cache = _runtime.cache
    if cache is None:
        cache = MemoryCache()
        _runtime.cache = cache
    return cache
