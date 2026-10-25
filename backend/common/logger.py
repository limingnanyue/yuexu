"""日志封装：控制台 + 滚动文件，统一格式。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_CONFIGURED = False

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_dir: str | Path = "logs",
    level: str = "INFO",
    debug: bool = False,
) -> None:
    """初始化全局日志（重复调用安全）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else getattr(logging, level.upper(), logging.INFO))

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(logging.DEBUG if debug else logging.INFO)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_path / "yuexu.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    root.addHandler(file_handler)

    error_handler = RotatingFileHandler(
        log_path / "error.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setFormatter(formatter)
    error_handler.setLevel(logging.ERROR)
    root.addHandler(error_handler)

    # 降低第三方库噪声（尤其是 DEBUG 模式下 aiosqlite / SQLAlchemy 的逐条 SQL 日志）
    for noisy in (
        "httpx",
        "httpcore",
        "urllib3",
        "aiosqlite",
        "sqlalchemy.engine",
        "sqlalchemy.pool",
        "asyncio",
        "websockets",
        "multipart",
        "apscheduler.executors.default",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str = "yuexu") -> logging.Logger:
    """获取模块日志器。"""
    return logging.getLogger(name)
