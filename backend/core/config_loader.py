"""配置加载：config_example.yaml 作为默认值，config.yaml 覆盖，支持环境变量与热更新。

约定：
- 所有模块统一通过 ``get_config()`` 读取配置，禁止硬编码密钥 / 地址；
- ``${ENV}`` / ``${ENV:-默认值}`` 占位符在加载时展开；
- 后台修改系统配置调用 ``update(..., persist=True)`` 写回 ``config.yaml``。
"""

from __future__ import annotations

import logging
import os
import re
import threading
from pathlib import Path
from typing import Any

import yaml

from backend.common.exceptions import ConfigError
from backend.common.utils import deep_merge

logger = logging.getLogger("yuexu.config")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")

_MISSING = object()


def _expand_env(value: Any) -> Any:
    """递归展开 ``${VAR}`` 占位符。"""
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default if default is not None else "")

        return _ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


class ConfigLoader:
    """YAML 配置加载器（单例使用，线程安全的读写）。"""

    def __init__(
        self,
        root: str | Path | None = None,
        config_file: str = "config.yaml",
        example_file: str = "config_example.yaml",
    ) -> None:
        self.root = Path(root) if root else PROJECT_ROOT
        self.example_path = self.root / example_file
        env_path = os.environ.get("YUEXU_CONFIG")
        self.path = Path(env_path) if env_path else self.root / config_file
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------
    # 加载 / 保存
    # ------------------------------------------------------------------
    def load(self) -> dict[str, Any]:
        """读取默认配置并叠加本地配置。"""
        if not self.example_path.exists():
            raise ConfigError(f"缺少默认配置模板：{self.example_path}")

        with self._lock:
            defaults = self._read_yaml(self.example_path)
            overrides: dict[str, Any] = {}
            if self.path.exists() and self.path != self.example_path:
                overrides = self._read_yaml(self.path)
            elif not self.path.exists():
                logger.warning("未找到 %s，当前使用 config_example.yaml 默认配置", self.path.name)

            self._data = _expand_env(deep_merge(defaults, overrides))
            logger.debug("配置加载完成：%s", self.path)
            return self._data

    def reload(self) -> dict[str, Any]:
        return self.load()

    def save(self, path: str | Path | None = None) -> Path:
        """将当前配置写回 YAML。"""
        target = Path(path) if path else self.path
        with self._lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("w", encoding="utf-8") as handle:
                yaml.safe_dump(
                    self._data,
                    handle,
                    allow_unicode=True,
                    sort_keys=False,
                    default_flow_style=False,
                )
        logger.info("配置已保存：%s", target)
        return target

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    @property
    def data(self) -> dict[str, Any]:
        with self._lock:
            return self._data

    def get(self, key: str, default: Any = None) -> Any:
        """按 ``a.b.c`` 路径读取配置。"""
        value: Any = self._data
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value

    def section(self, key: str) -> dict[str, Any]:
        value = self.get(key, {})
        return value if isinstance(value, dict) else {}

    def require(self, key: str) -> Any:
        value = self.get(key, _MISSING)
        if value is _MISSING:
            raise ConfigError(f"缺少必要配置项：{key}")
        return value

    def resolve_path(self, value: str) -> Path:
        """相对路径统一按项目根目录解析。"""
        path = Path(value)
        return path if path.is_absolute() else (self.root / path)

    # ------------------------------------------------------------------
    # 修改
    # ------------------------------------------------------------------
    def update(self, patch: dict[str, Any], persist: bool = True) -> dict[str, Any]:
        """深合并更新配置，可选写回文件。"""
        with self._lock:
            self._data = deep_merge(self._data, patch)
            if persist:
                self.save()
            return self._data

    def set(self, key: str, value: Any, persist: bool = True) -> dict[str, Any]:
        """按点路径设置单个配置项。"""
        patch: dict[str, Any] = {}
        cursor = patch
        parts = key.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
        return self.update(patch, persist=persist)

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"配置文件格式错误：{path}（{exc}）") from exc
        if not isinstance(data, dict):
            raise ConfigError(f"配置文件根节点必须是字典：{path}")
        return data


_config: ConfigLoader | None = None
_config_lock = threading.Lock()


def get_config() -> ConfigLoader:
    """获取全局配置单例。"""
    global _config
    if _config is None:
        with _config_lock:
            if _config is None:
                _config = ConfigLoader()
    return _config


def reset_config(root: str | Path | None = None) -> ConfigLoader:
    """测试用：重建配置单例。"""
    global _config
    with _config_lock:
        _config = ConfigLoader(root=root)
    return _config
