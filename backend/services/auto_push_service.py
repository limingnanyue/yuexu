"""旧固定推送任务的只读归档：V1.3 仅允许私聊随机惦记。"""

from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exceptions import NotFoundError, ValidationError
from backend.database.models import AutoPushTask
from backend.repositories.auto_push_repo import AutoPushRepo
from backend.repositories.log_repo import LogRepo
from backend.services.account_service import AccountService


class AutoPushService:
    def __init__(self, session: AsyncSession, cache=None, scheduler=None, factory=None):
        self.session = session
        self.repo = AutoPushRepo(session)
        self.log_repo = LogRepo(session)
        self.accounts = AccountService(session, factory=factory)

    async def list_page(self, page=1, page_size=20, **filters):
        return await self.repo.list_page(page, page_size, **filters)

    async def get_task(self, task_id: str) -> AutoPushTask:
        task = await self.repo.get(task_id)
        if task is None:
            raise NotFoundError("历史推送任务不存在")
        return task

    async def create_task(self, data: dict[str, Any], created_by=None):
        raise ValidationError("固定任务推送已停用，仅支持私聊随机惦记")

    async def update_task(self, task_id: str, data: dict[str, Any]):
        raise ValidationError("历史推送任务只读，不能修改或重新启用")

    async def delete_task(self, task_id: str):
        await self.repo.delete(await self.get_task(task_id))

    async def set_enabled(self, task_id: str, enabled: bool):
        if enabled:
            raise ValidationError("不能启用固定任务推送")
        task = await self.get_task(task_id)
        task.enabled = False
        task.next_run_at = None
        await self.session.flush()
        return task

    async def set_paused(self, task_id: str, paused: bool):
        if not paused:
            raise ValidationError("不能恢复固定任务推送")
        task = await self.set_enabled(task_id, False)
        task.paused = True
        return task

    async def bootstrap(self) -> int:
        result = await self.session.execute(update(AutoPushTask).values(
            enabled=False, paused=True, next_run_at=None,
        ).where(AutoPushTask.enabled.is_(True)))
        return result.rowcount

    def compute_next_run(self, task, base=None):
        return None

    async def run_due_tasks(self) -> int:
        await self.bootstrap()
        return 0

    async def execute_task(self, task: AutoPushTask) -> bool:
        task.enabled = False
        task.paused = True
        task.next_run_at = None
        task.last_error = "固定任务及群聊主动推送已停用"
        await self.log_repo.add_push(
            task_id=task.id, bot_id=task.bot_id, target_type=task.target_type,
            target_id=task.target_id, success=False, error=task.last_error,
        )
        await self.session.flush()
        return False
