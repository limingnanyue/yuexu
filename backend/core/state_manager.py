"""机器人账号在线状态管理：内存态 + 登录态快照。

适配器断线、重连、风控都通过本模块更新状态，后台通过 API 读取。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from backend.common.constants import ACCOUNT_STATUS_LABELS, AccountStatus
from backend.common.logger import get_logger
from backend.common.message import LoginQrcode
from backend.common.utils import dt_to_iso, now

logger = get_logger("yuexu.state")


@dataclass
class AccountRuntime:
    """单个账号的运行时状态。"""

    account_id: str
    status: AccountStatus = AccountStatus.OFFLINE
    account_no: str | None = None
    nickname: str | None = None
    connected_at: datetime | None = None
    last_heartbeat: datetime | None = None
    last_error: str | None = None
    reconnect_attempts: int = 0
    qrcode: LoginQrcode | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def status_label(self) -> str:
        return ACCOUNT_STATUS_LABELS.get(self.status.value, self.status.value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "status": self.status.value,
            "status_label": self.status_label,
            "account_no": self.account_no,
            "nickname": self.nickname,
            "connected_at": dt_to_iso(self.connected_at),
            "last_heartbeat": dt_to_iso(self.last_heartbeat),
            "last_error": self.last_error,
            "reconnect_attempts": self.reconnect_attempts,
            "has_qrcode": self.qrcode is not None,
            "qrcode": self.qrcode.model_dump(exclude_none=True) if self.qrcode else None,
        }


class AccountStateManager:
    """账号状态集中管理（单进程内存）。"""

    def __init__(self) -> None:
        self._states: dict[str, AccountRuntime] = {}

    # ------------------------------------------------------------------
    def register(self, account_id: str, account_no: str | None = None) -> AccountRuntime:
        runtime = self._states.get(account_id)
        if runtime is None:
            runtime = AccountRuntime(account_id=account_id, account_no=account_no)
            self._states[account_id] = runtime
        elif account_no:
            runtime.account_no = account_no
        return runtime

    def unregister(self, account_id: str) -> None:
        self._states.pop(account_id, None)

    def get(self, account_id: str) -> AccountRuntime | None:
        return self._states.get(account_id)

    def require(self, account_id: str) -> AccountRuntime:
        return self.register(account_id)

    def list(self) -> list[AccountRuntime]:
        return list(self._states.values())

    def online_count(self) -> int:
        return sum(
            1 for runtime in self._states.values()
            if runtime.status == AccountStatus.ONLINE
        )

    def is_online(self, account_id: str) -> bool:
        runtime = self._states.get(account_id)
        return bool(runtime and runtime.status == AccountStatus.ONLINE)

    # ------------------------------------------------------------------
    def set_status(
        self,
        account_id: str,
        status: AccountStatus,
        *,
        error: str | None = None,
    ) -> AccountRuntime:
        runtime = self.register(account_id)
        runtime.status = status
        if error is not None:
            runtime.last_error = error
        if status != AccountStatus.ONLINE:
            runtime.qrcode = None if status == AccountStatus.OFFLINE else runtime.qrcode
        logger.info("账号 %s 状态更新：%s%s", account_id, runtime.status_label,
                    f"（{error}）" if error else "")
        return runtime

    def mark_waiting_qr(self, account_id: str, qrcode: LoginQrcode) -> AccountRuntime:
        runtime = self.register(account_id)
        runtime.status = AccountStatus.WAITING_QR
        runtime.qrcode = qrcode
        runtime.last_error = None
        return runtime

    def mark_online(
        self,
        account_id: str,
        *,
        account_no: str | None = None,
        nickname: str | None = None,
    ) -> AccountRuntime:
        runtime = self.register(account_id, account_no=account_no)
        runtime.status = AccountStatus.ONLINE
        runtime.connected_at = now()
        runtime.last_heartbeat = now()
        runtime.last_error = None
        runtime.reconnect_attempts = 0
        runtime.qrcode = None
        if account_no:
            runtime.account_no = account_no
        if nickname:
            runtime.nickname = nickname
        return runtime

    def mark_offline(self, account_id: str, reason: str | None = None) -> AccountRuntime:
        runtime = self.set_status(account_id, AccountStatus.OFFLINE, error=reason)
        runtime.connected_at = None
        return runtime

    def mark_error(self, account_id: str, error: str) -> AccountRuntime:
        runtime = self.set_status(account_id, AccountStatus.ERROR, error=error)
        runtime.reconnect_attempts += 1
        return runtime

    def heartbeat(self, account_id: str) -> None:
        runtime = self._states.get(account_id)
        if runtime:
            runtime.last_heartbeat = now()

    def reset_reconnect(self, account_id: str) -> None:
        runtime = self._states.get(account_id)
        if runtime:
            runtime.reconnect_attempts = 0

    def snapshot(self) -> list[dict[str, Any]]:
        return [runtime.to_dict() for runtime in self._states.values()]
