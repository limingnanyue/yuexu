"""系统设置接口：仪表盘、配置、备份、任务列表、健康检查。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel

from backend.dependencies import (
    get_system_service,
    require_admin,
    require_owner,
)
from backend.services.system_service import SystemService

router = APIRouter(prefix="/api/system", tags=["系统设置"])


class RestoreRequest(BaseModel):
    name: str


@router.get("/health", summary="健康检查（无需登录）")
async def health():
    """无鉴权健康检查，供 Windows 启动器 / 容器探针使用。"""
    from backend.common.utils import now
    from backend.core.runtime import get_runtime
    from backend.database.db import check_database

    runtime = get_runtime()
    database_ok = await check_database()
    return {
        "status": "ok" if database_ok else "degraded",
        "database": "up" if database_ok else "down",
        "cache": getattr(getattr(runtime, "cache", None), "name", "memory"),
        "scheduler": runtime.scheduler.running,
        "online_accounts": runtime.state_manager.online_count(),
        "time": now().isoformat(timespec="seconds"),
    }


@router.get("/dashboard", summary="仪表盘统计")
async def dashboard(
    _=Depends(require_admin),
    service: SystemService = Depends(get_system_service),
):
    return await service.dashboard()


@router.get("/info", summary="系统信息")
async def info(
    _=Depends(require_admin),
    service: SystemService = Depends(get_system_service),
):
    return await service.info()


@router.get("/config", summary="读取系统配置（密钥脱敏）")
async def get_config_api(
    _=Depends(require_admin),
    service: SystemService = Depends(get_system_service),
):
    return service.public_config()


@router.put("/config", summary="更新系统配置")
async def update_config_api(
    patch: dict[str, Any] = Body(...),
    _=Depends(require_owner),
    service: SystemService = Depends(get_system_service),
):
    return service.update_config(patch)


@router.get("/jobs", summary="定时任务列表")
async def list_jobs(_=Depends(require_admin)):
    from backend.core.runtime import get_runtime

    return get_runtime().scheduler.jobs()


@router.get("/backups", summary="备份文件列表")
async def list_backups(
    _=Depends(require_admin),
    service: SystemService = Depends(get_system_service),
):
    return await service.list_backups()


@router.post("/backups", summary="立即备份数据库")
async def create_backup(
    _=Depends(require_owner),
    service: SystemService = Depends(get_system_service),
):
    return await service.backup_database()


@router.post("/backups/restore", summary="从备份恢复数据库")
async def restore_backup(
    payload: RestoreRequest,
    _=Depends(require_owner),
    service: SystemService = Depends(get_system_service),
):
    return await service.restore_backup(payload.name)


@router.get("/cache", summary="缓存统计")
async def cache_stats(
    _=Depends(require_admin),
    service: SystemService = Depends(get_system_service),
):
    return await service.cache_stats()
