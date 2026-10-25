"""适配器工厂：按账号平台类型创建 / 缓存适配器实例。

扩展方式::

    from backend.adapters.adapter_factory import adapter_factory
    adapter_factory.register("telegram", MyTelegramAdapter)
"""

from __future__ import annotations

from backend.adapters.base_adapter import AdapterOptions, BaseAdapter
from backend.common.constants import Platform
from backend.common.logger import get_logger

logger = get_logger("yuexu.adapter.factory")


class AdapterFactory:
    """适配器注册表 + 实例缓存。"""

    def __init__(self) -> None:
        self._registry: dict[str, type[BaseAdapter]] = {}
        self._instances: dict[str, BaseAdapter] = {}

    # ------------------------------------------------------------------
    def register(self, platform: str, adapter_class: type[BaseAdapter]) -> None:
        self._registry[platform] = adapter_class

    def platforms(self) -> list[str]:
        return list(self._registry.keys())

    def is_supported(self, platform: str) -> bool:
        return platform in self._registry

    # ------------------------------------------------------------------
    def get_or_create(self, options: AdapterOptions) -> BaseAdapter:
        """按 account_id 缓存实例；配置变更后可调用 ``reset`` 重建。"""
        adapter = self._instances.get(options.account_id)
        if adapter is None:
            adapter_class = self._registry.get(options.platform)
            if adapter_class is None:
                raise ValueError(f"暂不支持的平台类型：{options.platform}")
            adapter = adapter_class(options)
            self._instances[options.account_id] = adapter
            logger.info("创建适配器：%s（%s）", options.account_id, options.platform)
        return adapter

    def get(self, account_id: str) -> BaseAdapter | None:
        return self._instances.get(account_id)

    def register_instance(self, adapter: BaseAdapter) -> None:
        """注册外部构造的适配器实例（测试 / 自定义连接复用）。"""
        self._instances[adapter.account_id] = adapter

    async def reset(self, account_id: str) -> None:
        adapter = self._instances.pop(account_id, None)
        if adapter is not None:
            try:
                await adapter.close()
            except Exception:  # noqa: BLE001
                logger.exception("关闭适配器失败：%s", account_id)

    async def close_all(self) -> None:
        for account_id in list(self._instances):
            await self.reset(account_id)


adapter_factory = AdapterFactory()

# 注册内置平台（延迟导入避免循环依赖）
from backend.adapters.napcat_adapter import NapCatAdapter  # noqa: E402
from backend.adapters.gewechat_adapter import GewechatAdapter  # noqa: E402
from backend.adapters.clawbot_adapter import ClawBotAdapter  # noqa: E402
from backend.adapters.qq_bot_adapter import QQBotAdapter  # noqa: E402

adapter_factory.register(Platform.QQ.value, NapCatAdapter)
adapter_factory.register(Platform.WECHAT.value, GewechatAdapter)
adapter_factory.register(Platform.QQ_BOT.value, QQBotAdapter)
adapter_factory.register(Platform.WECHAT_CLAWBOT.value, ClawBotAdapter)

__all__ = ["AdapterFactory", "adapter_factory", "AdapterOptions", "BaseAdapter"]
