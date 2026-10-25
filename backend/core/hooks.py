"""扩展钩子：分发链路预留的插件接入点（开发文档第 11 章）。

新增画图、音乐、小游戏等能力时，只需注册钩子，不必改动主链路。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Awaitable, Callable

from backend.common.logger import get_logger

logger = get_logger("yuexu.hooks")

# 已知钩子事件
HOOK_EVENT_RECEIVED = "dispatch.received"        # 收到消息，过滤前
HOOK_PRE_LLM = "llm.pre"                         # 调用大模型前，可改写 prompt
HOOK_POST_LLM = "llm.post"                       # 拿到回复后，可改写内容
HOOK_PRE_SEND = "send.pre"                       # 发送前，可追加/拦截消息段
HOOK_POST_SEND = "send.post"                     # 发送后
HOOK_PUSH_BEFORE = "push.before"                 # 自动推送发送前

HookHandler = Callable[..., Awaitable[Any]]


class HookRegistry:
    """异步钩子注册表。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[HookHandler]] = defaultdict(list)

    def register(self, event: str, handler: HookHandler) -> Callable[[], None]:
        """注册钩子，返回取消注册函数。"""
        self._handlers[event].append(handler)
        logger.debug("注册钩子 %s -> %s", event, getattr(handler, "__name__", handler))

        def unregister() -> None:
            self.unregister(event, handler)

        return unregister

    def unregister(self, event: str, handler: HookHandler) -> None:
        handlers = self._handlers.get(event, [])
        if handler in handlers:
            handlers.remove(handler)

    def clear(self) -> None:
        self._handlers.clear()

    def handlers(self, event: str) -> list[HookHandler]:
        return list(self._handlers.get(event, []))

    async def emit(self, hook_name: str, **payload: Any) -> list[Any]:
        """串行触发钩子，单个钩子异常不影响主链路。"""
        results: list[Any] = []
        for handler in self.handlers(hook_name):
            try:
                results.append(await handler(**payload))
            except Exception:  # noqa: BLE001
                logger.exception("钩子执行异常：%s", hook_name)
        return results


hook_registry = HookRegistry()


def get_hooks() -> HookRegistry:
    return hook_registry
