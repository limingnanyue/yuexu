"""系统服务：仪表盘统计、健康检查、配置读写、数据备份、日志清理。"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.cache import CacheBackend
from backend.common.exceptions import NotFoundError, ValidationError
from backend.common.logger import get_logger
from backend.common.utils import now
from backend.core.config_loader import get_config
from backend.core.runtime import get_runtime
from backend.database.db import check_database
from backend.database.models import (
    AiRequestLog,
    MessageLog,
    SearchLog,
    UserPushRecord,
    UserPushState,
)
from backend.repositories.account_repo import AccountRepo
from backend.services.context_service import ContextService
from backend.repositories.log_repo import LogRepo
from backend.repositories.memory_repo import MemoryRepo

logger = get_logger("yuexu.service.system")

def _is_secret_key(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered in {"password", "token", "secret", "api_key", "jwt_secret", "adapter_token"}
        or lowered.endswith(("_key", "_token", "_secret", "_password"))
    )


class SystemService:
    """系统级只读统计与配置管理。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.config = get_config()
        self.runtime = get_runtime()
        self.logs = LogRepo(session)

    # ------------------------------------------------------------------
    # 仪表盘
    # ------------------------------------------------------------------
    async def dashboard(self) -> dict[str, Any]:
        today = now().replace(hour=0, minute=0, second=0, microsecond=0)
        accounts = await AccountRepo(self.session).list_all()
        online = self.runtime.state_manager.online_count()

        message_total = await self.logs.count_since(MessageLog, today)
        message_in = await self.logs.count_since(MessageLog, today, direction="in")
        ai_total = await self.logs.count_since(AiRequestLog, today)
        ai_failed = await self.logs.count_since(AiRequestLog, today, success=False)
        prompt_tokens, completion_tokens = (await self.session.execute(
            select(
                func.coalesce(func.sum(AiRequestLog.prompt_tokens), 0),
                func.coalesce(func.sum(AiRequestLog.completion_tokens), 0),
            ).where(AiRequestLog.created_at >= today)
        )).one()
        search_total = await self.logs.count_since(SearchLog, today)
        push_success = await self.session.scalar(select(func.count()).select_from(UserPushRecord).where(
            UserPushRecord.send_time >= today, UserPushRecord.sent.is_(True),
        ))
        push_failed = await self.session.scalar(select(func.count()).select_from(UserPushRecord).where(
            UserPushRecord.send_time >= today, UserPushRecord.sent.is_(False),
        ))
        push_total = await self.session.scalar(select(func.count()).select_from(UserPushState).where(UserPushState.chat_type == "private"))
        push_enabled = await self.session.scalar(select(func.count()).select_from(UserPushState).where(
            UserPushState.chat_type == "private", UserPushState.user_push_switch.is_(True),
        ))
        memory_total = await MemoryRepo(self.session).count_all()
        cache = getattr(self.runtime, "cache", None)
        context_sessions = await ContextService().repo.count() if cache else 0

        return {
            "accounts": {
                "total": len(accounts),
                "online": online,
                "offline": max(0, len(accounts) - online),
            },
            "today": {
                "messages": message_total,
                "messages_in": message_in,
                "messages_out": max(0, message_total - message_in),
                "ai_calls": ai_total,
                "ai_failed": ai_failed,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "tokens": prompt_tokens + completion_tokens,
                "search_calls": search_total,
                "push_success": push_success,
                "push_failed": push_failed,
            },
            "push": {
                "enabled_tasks": push_enabled,
                "total_tasks": push_total,
            },
            "memory": {"total": memory_total},
            "context": {"sessions": context_sessions},
            "service": {
                "database": "up" if await check_database() else "down",
                "cache": getattr(getattr(self.runtime, "cache", None), "name", "memory"),
                "scheduler": "running" if self.runtime.scheduler.running else "stopped",
                "version": str(self.config.get("app.version", "0.1.0")),
            },
            "generated_at": now().isoformat(timespec="seconds"),
        }

    # ------------------------------------------------------------------
    # 健康检查 / 系统信息
    # ------------------------------------------------------------------
    async def health(self) -> dict[str, Any]:
        database_ok = await check_database()
        cache_name = getattr(getattr(self.runtime, "cache", None), "name", "memory")
        return {
            "status": "ok" if database_ok else "degraded",
            "database": "up" if database_ok else "down",
            "cache": cache_name,
            "scheduler": self.runtime.scheduler.running,
            "online_accounts": self.runtime.state_manager.online_count(),
            "version": str(self.config.get("app.version", "0.1.0")),
            "time": now().isoformat(timespec="seconds"),
        }

    async def info(self) -> dict[str, Any]:
        import platform as platform_module
        import sys

        database_url = str(self.config.get("database.url", ""))
        return {
            "app": self.config.get("app.name", "月叙"),
            "version": self.config.get("app.version", "0.1.0"),
            "env": self.config.get("app.env", "dev"),
            "python": sys.version.split()[0],
            "platform": platform_module.platform(),
            "database": self._mask_url(database_url),
            "cache": getattr(getattr(self.runtime, "cache", None), "name", "memory"),
            "config_path": str(self.config.path),
            "scheduler_jobs": len(self.runtime.scheduler.jobs()),
            "uptime_tasks": len(self.runtime.state_manager.list()),
        }

    # ------------------------------------------------------------------
    # 配置读写
    # ------------------------------------------------------------------
    def public_config(self) -> dict[str, Any]:
        """返回脱敏后的配置（密钥只显示掩码）。"""
        return self._mask_dict(self.config.data)

    def update_config(self, patch: dict[str, Any]) -> dict[str, Any]:
        """更新配置并写回 config.yaml；占位掩码值不会被覆盖。"""
        if not isinstance(patch, dict):
            raise ValidationError("配置必须是对象")
        cleaned = self._strip_masks(patch, self.config.data)
        self.config.update(cleaned, persist=True)
        logger.info("系统配置已更新：%s", ", ".join(sorted(cleaned.keys())))
        return self.public_config()

    # ------------------------------------------------------------------
    # 备份 / 恢复
    # ------------------------------------------------------------------
    @property
    def backup_dir(self) -> Path:
        path = self.config.resolve_path(
            str(self.config.get("scheduler.backup_dir", "data/backups"))
        )
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def backup_database(self) -> dict[str, Any]:
        url = str(self.config.get("database.url", ""))
        if not url.startswith("sqlite"):
            raise ValidationError("当前数据库不是 SQLite，请使用数据库自带备份工具")
        database = make_url(url).database
        if not database or database == ":memory:":
            raise ValidationError("无法定位数据库文件")
        source = Path(database).expanduser().resolve()
        if not source.exists():
            raise NotFoundError("数据库文件不存在")

        stamp = now().strftime("%Y%m%d_%H%M%S")
        target = self.backup_dir / f"yuexu_{stamp}.db"
        await asyncio.to_thread(self._sqlite_backup, source, target)
        self._cleanup_backups(keep=int(self.config.get("scheduler.backup_keep", 7)))
        logger.info("数据库备份完成：%s", target)
        return {"file": target.name, "path": str(target), "size": target.stat().st_size}

    async def list_backups(self) -> list[dict[str, Any]]:
        backups = sorted(self.backup_dir.glob("yuexu_*.db"), reverse=True)
        return [
            {
                "name": file.name,
                "size": file.stat().st_size,
                "created_at": datetime.fromtimestamp(file.stat().st_mtime).isoformat(
                    timespec="seconds"
                ),
            }
            for file in backups
        ]

    async def restore_backup(self, name: str) -> dict[str, Any]:
        """从备份文件热恢复 SQLite 数据库（使用 sqlite backup API）。"""
        if "/" in name or "\\" in name or ".." in name:
            raise ValidationError("备份文件名不合法")
        source = self.backup_dir / name
        if not source.exists():
            raise NotFoundError("备份文件不存在")

        url = str(self.config.get("database.url", ""))
        if not url.startswith("sqlite"):
            raise ValidationError("仅支持 SQLite 热恢复")
        database = make_url(url).database
        if not database:
            raise ValidationError("无法定位数据库文件")
        target = Path(database).expanduser().resolve()
        await asyncio.to_thread(self._sqlite_restore, source, target)
        logger.warning("数据库已从备份恢复：%s -> %s", source.name, target)
        return {"message": "恢复完成，建议重启服务", "file": source.name}

    @staticmethod
    def _sqlite_backup(source: Path, target: Path) -> None:
        source_conn = sqlite3.connect(str(source), timeout=30)
        target_conn = sqlite3.connect(str(target), timeout=30)
        try:
            source_conn.backup(target_conn)
        finally:
            source_conn.close()
            target_conn.close()

    @staticmethod
    def _sqlite_restore(source: Path, target: Path) -> None:
        source_conn = sqlite3.connect(str(source), timeout=30)
        target_conn = sqlite3.connect(str(target), timeout=30)
        try:
            source_conn.backup(target_conn)
        finally:
            source_conn.close()
            target_conn.close()

    def _cleanup_backups(self, keep: int) -> None:
        if keep <= 0:
            return
        backups = sorted(self.backup_dir.glob("yuexu_*.db"), reverse=True)
        for file in backups[keep:]:
            try:
                file.unlink()
            except OSError:
                logger.warning("删除旧备份失败：%s", file)

    # ------------------------------------------------------------------
    # 日志清理 / 缓存统计
    # ------------------------------------------------------------------
    async def cleanup_logs(self, retention_days: int | None = None) -> dict[str, int]:
        days = retention_days if retention_days is not None else int(
            self.config.get("scheduler.log_retention_days", 30)
        )
        if days <= 0:
            return {}
        from backend.services.log_service import LogService

        return await LogService(self.session).cleanup(days)

    async def cache_stats(self) -> dict[str, Any]:
        cache: CacheBackend | None = getattr(self.runtime, "cache", None)
        return {
            "backend": getattr(cache, "name", "memory"),
            "context_sessions": await ContextService().repo.count() if cache else 0,
        }

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _mask_url(url: str) -> str:
        if "://" not in url:
            return url
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            credentials, host = rest.split("@", 1)
            user = credentials.split(":", 1)[0]
            return f"{scheme}://{user}:***@{host}"
        return url

    def _mask_dict(self, data: Any, key: str = "") -> Any:
        if isinstance(data, dict):
            return {k: self._mask_dict(v, k) for k, v in data.items()}
        if isinstance(data, list):
            return [self._mask_dict(item, key) for item in data]
        if isinstance(data, str) and key and _is_secret_key(key):
            if not data:
                return ""
            if len(data) <= 8:
                return "*" * len(data)
            return f"{data[:4]}{'*' * max(len(data) - 8, 2)}{data[-4:]}"
        return data

    def _strip_masks(self, patch: dict[str, Any], current: Any = None) -> dict[str, Any]:
        """忽略前端回传的掩码占位值，避免把 ``****`` 写回配置。"""
        cleaned: dict[str, Any] = {}
        current_dict = current if isinstance(current, dict) else {}
        for key, value in patch.items():
            current_value = current_dict.get(key)
            if isinstance(value, dict):
                nested = self._strip_masks(value, current_value)
                if nested:
                    cleaned[key] = nested
            elif isinstance(value, str) and value and current_value and "*" in value:
                # 掩码长度与原值一致时判定为「未修改」，跳过写回
                if len(value) == len(str(current_value)):
                    continue
                cleaned[key] = value
            else:
                cleaned[key] = value
        return cleaned
