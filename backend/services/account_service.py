"""账号与登录（开发文档 4.1）：扫码登录、多账号、状态管理、独立配置绑定。"""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.adapter_factory import AdapterFactory
from backend.adapters.base_adapter import AdapterOptions, BaseAdapter
from backend.common.constants import ACCOUNT_STATUS_LABELS, PLATFORM_LABELS, AccountStatus, Platform
from backend.common.exceptions import AppError, NotFoundError, ValidationError
from backend.common.logger import get_logger
from backend.common.utils import now
from backend.core.config_loader import get_config
from backend.core.runtime import get_runtime
from backend.core.state_manager import AccountStateManager
from backend.database.models import BotAccount, MemoryLibrary
from backend.repositories.account_repo import AccountRepo
from backend.repositories.log_repo import LogRepo
from backend.repositories.memory_library_repo import MemoryLibraryRepo

logger = get_logger("yuexu.service.account")

# 取码按账号加锁：并发请求只取一次二维码，避免生成两个登录会话互相覆盖。
_qrcode_locks: dict[str, asyncio.Lock] = {}


class AccountService:
    """机器人账号服务。"""

    def __init__(
        self,
        session: AsyncSession,
        state_manager: AccountStateManager | None = None,
        factory: AdapterFactory | None = None,
    ) -> None:
        self.session = session
        self.repo = AccountRepo(session)
        self.log_repo = LogRepo(session)
        self.config = get_config()
        runtime = get_runtime()
        self.state = state_manager or runtime.state_manager
        self.factory = factory or runtime.adapter_factory

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def list_accounts(self) -> list[dict[str, Any]]:
        accounts = await self.repo.list_all()
        return [self._to_dict(account) for account in accounts]

    async def get_account(self, account_id: str) -> BotAccount:
        account = await self.repo.get(account_id)
        if not account:
            raise NotFoundError("机器人账号不存在")
        return account

    async def get_detail(self, account_id: str) -> dict[str, Any]:
        return self._to_dict(await self.get_account(account_id))

    async def list_memory_libraries(self) -> list[dict[str, Any]]:
        return await MemoryLibraryRepo(self.session).catalog()

    async def _validate_memory_library(self, library_id: str, platform: str) -> None:
        repo = MemoryLibraryRepo(self.session)
        await repo.ensure_legacy()
        library = await repo.get(library_id)
        if library is None:
            raise NotFoundError("记忆库不存在，请重新选择")
        if not library.platform:
            bound_library = func.coalesce(func.nullif(BotAccount.memory_library_id, ""), BotAccount.id)
            conflicts = select(BotAccount.id).where(bound_library == library_id, BotAccount.platform != platform)
            await self.session.execute(update(MemoryLibrary).where(
                MemoryLibrary.id == library_id, MemoryLibrary.platform == "", ~exists(conflicts),
            ).values(platform=platform))
            await self.session.refresh(library, ["platform"])
        if library.platform != platform:
            raise ValidationError("记忆库只能绑定相同接入方式的账号，避免不同平台的用户 ID 混用")

    # ------------------------------------------------------------------
    # 增删改
    # ------------------------------------------------------------------
    async def create_account(self, data: dict[str, Any]) -> BotAccount:
        payload = self._clean_payload(data, creating=True)
        if payload.get("memory_library_id"):
            await self._validate_memory_library(payload["memory_library_id"], payload["platform"])
        account = await self.repo.create(**payload, status=AccountStatus.OFFLINE.value)
        await MemoryLibraryRepo(self.session).create(id=account.id, name=account.name, platform=account.platform)
        self.state.register(account.id)
        await self.log_repo.add_operation(
            module="account", action="创建账号", detail=f"{account.name}（{account.platform}）"
        )
        logger.info("创建机器人账号：%s", account.id)
        return account

    async def update_account(self, account_id: str, data: dict[str, Any]) -> BotAccount:
        account = await self.get_account(account_id)
        payload = self._clean_payload(data, creating=False)
        platform = payload.get("platform", account.platform)
        if "memory_library_id" in payload or platform != account.platform:
            await self._validate_memory_library(
                payload.get("memory_library_id", account.memory_library_id) or account.id, platform,
            )
        if payload.get("adapter_config", {}).get("managed") and platform != Platform.QQ.value:
            raise ValidationError("当前仅 QQ 个人账号支持自动准备登录环境")
        if platform in {Platform.QQ_BOT.value, Platform.WECHAT_CLAWBOT.value}:
            payload["settings"] = {**(account.settings or {}), **payload.get("settings", {}), "voice": False, "emoji": False}
        if "adapter_config" in payload:
            payload["adapter_config"] = {**(account.adapter_config or {}), **payload["adapter_config"]}
            if not payload["adapter_config"].get("webui_token") and (account.adapter_config or {}).get("webui_token"):
                payload["adapter_config"]["webui_token"] = account.adapter_config["webui_token"]
        if platform == Platform.QQ_BOT.value and payload.get("adapter_config", {}).get("transport", "websocket") not in {"websocket", "webhook"}:
            raise ValidationError("QQ 机器人接收方式只支持长连接或事件回调")
        connection_changed = any(key in payload and payload[key] != getattr(account, key) for key in (
            "platform", "adapter_base_url", "adapter_token", "adapter_config",
        ))
        if connection_changed:
            from backend.services.account_setup_service import cancel_prepare, is_managed
            if is_managed(account):
                await cancel_prepare(account_id)
            await self.factory.reset(account_id)
            self.state.mark_offline(account_id)
            payload["status"] = AccountStatus.OFFLINE.value
        account = await self.repo.update(account, **payload)
        await self.log_repo.add_operation(
            module="account", action="更新账号配置", detail=account.name
        )
        return account

    async def delete_account(self, account_id: str) -> None:
        account = await self.get_account(account_id)
        await MemoryLibraryRepo(self.session).ensure_legacy()
        from backend.services.account_setup_service import cancel_prepare, is_managed
        if is_managed(account):
            await cancel_prepare(account_id)
        await self.factory.reset(account_id)
        self.state.unregister(account_id)
        await self.repo.delete(account)
        await self.log_repo.add_operation(module="account", action="删除账号", detail=account.name)

    # ------------------------------------------------------------------
    # 登录流程
    # ------------------------------------------------------------------
    async def prepare_login(self, account_id: str, *, start: bool = False) -> dict[str, Any]:
        from backend.services.account_setup_service import get_status, is_managed, start_prepare
        account = await self.get_account(account_id)
        if not is_managed(account):
            return {"account_id": account_id, "status": "ready", "stage": "ready", "message": "可以开始扫码"}
        return start_prepare(account_id) if start else get_status(account_id)

    async def request_qrcode(self, account_id: str, *, refresh=False) -> dict[str, Any]:
        account = await self.get_account(account_id)
        from backend.services.account_setup_service import get_status, is_managed, start_prepare
        if is_managed(account) and get_status(account_id)["status"] != "ready":
            progress = start_prepare(account_id)
            raise AppError(progress["message"], status_code=409, code="LOGIN_PREPARING", detail=progress)
        async with _qrcode_locks.setdefault(account_id, asyncio.Lock()):
            adapter = self.build_adapter(account)
            if adapter.receive_task:
                await adapter.close()
            fetch_qr = getattr(adapter, "refresh_login_qrcode", adapter.fetch_login_qrcode) if refresh else adapter.fetch_login_qrcode
            qrcode = await fetch_qr()
            self.state.mark_waiting_qr(account_id, qrcode)
            changes = {"status": AccountStatus.WAITING_QR.value, "last_error": None}
            if account.platform == Platform.WECHAT.value:
                changes.update(adapter_token=adapter.options.token,
                               adapter_config={**(account.adapter_config or {}),
                                               "app_id": adapter.options.config.get("app_id", ""),
                                               "login_uuid": adapter.options.config.get("login_uuid", "")})
            await self.repo.update(account, **changes)

        await self.log_repo.add_operation(
            module="account", action="生成登录二维码", detail=account.name
        )
        return {
            "account_id": account_id,
            "status": AccountStatus.WAITING_QR.value,
            "status_label": ACCOUNT_STATUS_LABELS[AccountStatus.WAITING_QR.value],
            "image_base64": qrcode.image_base64,
            "image_url": qrcode.image_url,
            "expires_in": qrcode.expires_in,
        }

    async def poll_login(self, account_id: str, verify_code: str | None = None) -> dict[str, Any]:
        account = await self.get_account(account_id)
        adapter = self.build_adapter(account)
        if verify_code is not None:
            if account.platform != Platform.WECHAT_CLAWBOT.value or not verify_code.isdigit() or not 4 <= len(verify_code) <= 12:
                raise ValidationError("请输入微信手机端显示的数字验证码")
            login_state = await adapter.check_login_status(verify_code=verify_code)
        else:
            login_state = await adapter.check_login_status()

        if login_state.status == AccountStatus.ONLINE.value:
            if not account.account_no and account.platform in {Platform.QQ.value, Platform.WECHAT_CLAWBOT.value}:
                await self.repo.update(account, auto_connect=True)
            if account.platform == Platform.WECHAT_CLAWBOT.value:
                await self.repo.update(account, adapter_token=adapter.options.token,
                                       adapter_base_url=adapter.options.base_url,
                                       adapter_config={**(account.adapter_config or {}), **adapter.options.config})
            self.state.mark_online(
                account_id,
                account_no=login_state.account_no,
                nickname=login_state.nickname,
            )
            await self.repo.update(
                account,
                status=AccountStatus.ONLINE.value,
                account_no=login_state.account_no or account.account_no,
                last_online_at=now(),
                last_error=None,
            )
            await self.log_repo.add_operation(
                module="account",
                action="扫码登录成功",
                detail=f"{account.name}（{login_state.account_no or ''}）",
            )
            self._start_receiver(adapter)
        elif login_state.status in {AccountStatus.SCANNING.value, AccountStatus.WAITING_QR.value}:
            # 等待扫码 / 已扫码阶段前端每 2.5s 轮询一次，仅在状态变化时落库，避免写放大。
            if account.status != login_state.status:
                await self.repo.update(account, status=login_state.status)
            self.state.set_status(account_id, AccountStatus(login_state.status))
        else:
            await self.repo.update(
                account, status=login_state.status, last_error=login_state.message
            )
            self.state.set_status(
                account_id, AccountStatus(login_state.status), error=login_state.message
            )

        return {
            "account_id": account_id,
            "status": login_state.status,
            "message": login_state.message,
            "account_no": login_state.account_no,
            "nickname": login_state.nickname,
            "needs_verify_code": bool(login_state.raw.get("needs_verify_code")),
        }

    async def logout(self, account_id: str) -> dict[str, Any]:
        account = await self.get_account(account_id)
        from backend.services.account_setup_service import cancel_prepare, is_managed
        try:
            if is_managed(account):
                await cancel_prepare(account_id)
            else:
                adapter = self.factory.get(account_id) or self.build_adapter(account)
                await adapter.logout()
        finally:
            await self.factory.reset(account_id)
            self.state.mark_offline(account_id)
            await self.repo.update(account, status=AccountStatus.OFFLINE.value, auto_connect=False)
            await self.log_repo.add_operation(
                module="account", action="主动下线", detail=account.name
            )
        return {"account_id": account_id, "status": AccountStatus.OFFLINE.value}

    async def reconnect(self, account_id: str) -> dict[str, Any]:
        account = await self.get_account(account_id)
        from backend.services.account_setup_service import get_status, is_managed, start_prepare
        if is_managed(account) and get_status(account_id)["status"] != "ready":
            progress = start_prepare(account_id)
            return {**progress, "success": False, "preparing": True}
        adapter = self.build_adapter(account)
        self.state.set_status(account_id, AccountStatus.CONNECTING)
        try:
            if is_managed(account) or (account.platform == Platform.QQ.value and (account.adapter_config or {}).get("runtime") == "qq_av"):
                login_state = await adapter.check_login_status()
                if login_state.status != AccountStatus.ONLINE.value:
                    self.state.set_status(account_id, AccountStatus(login_state.status))
                    await self.repo.update(account, status=login_state.status, last_error=None if login_state.status in {
                        AccountStatus.WAITING_QR.value, AccountStatus.SCANNING.value,
                    } else login_state.message)
                    return {"account_id": account_id, "success": False, "status": login_state.status,
                            "needs_qrcode": login_state.status in {AccountStatus.WAITING_QR.value, AccountStatus.SCANNING.value},
                            "message": login_state.message, "error": login_state.message}
                info = {"user_id": login_state.account_no, "nickname": login_state.nickname}
            else:
                info = await adapter.get_self_info()
            if account.platform == Platform.QQ_BOT.value and adapter.options.config.get("transport", "websocket") == "websocket":
                await adapter.open_gateway()
        except Exception as exc:  # noqa: BLE001
            self.state.mark_error(account_id, str(exc))
            await self.repo.update(
                account, status=AccountStatus.ERROR.value, last_error=str(exc)[:500]
            )
            return {"account_id": account_id, "success": False, "error": str(exc)}

        account_no = str(info.get("user_id") or info.get("wxid") or account.account_no or "")
        nickname = str(info.get("nickname") or "")
        self.state.mark_online(account_id, account_no=account_no, nickname=nickname)
        self.state.reset_reconnect(account_id)
        await self.repo.update(
            account,
            status=AccountStatus.ONLINE.value,
            account_no=account_no or account.account_no,
            last_online_at=now(),
            last_error=None,
        )
        self._start_receiver(adapter)
        return {
            "account_id": account_id,
            "success": True,
            "status": AccountStatus.ONLINE.value,
            "account_no": account_no,
            "nickname": nickname,
        }

    async def refresh_status(self, account_id: str) -> dict[str, Any]:
        return await self.poll_login(account_id)

    # ------------------------------------------------------------------
    # 群 / 好友
    # ------------------------------------------------------------------
    async def get_groups(self, account_id: str) -> list[dict[str, Any]]:
        account = await self.get_account(account_id)
        return await self.build_adapter(account).get_group_list()

    async def get_friends(self, account_id: str) -> list[dict[str, Any]]:
        account = await self.get_account(account_id)
        return await self.build_adapter(account).get_friend_list()

    # ------------------------------------------------------------------
    # 启动 / 重连
    # ------------------------------------------------------------------
    async def bootstrap(self) -> None:
        """启动时恢复账号状态，按 auto_connect 自动重连。"""
        accounts = await self.repo.list_all()
        for account in accounts:
            self.state.register(account.id, account.account_no)
            self.state.set_status(account.id, AccountStatus.OFFLINE)
        logger.info("已加载 %s 个机器人账号", len(accounts))
        for account in accounts:
            if account.auto_connect:
                try:
                    await self.reconnect(account.id)
                except Exception:  # noqa: BLE001
                    logger.exception("账号自动重连失败：%s", account.id)

    async def reconnect_pending(self) -> int:
        """后台巡检：对设置了自动连接的离线账号尝试重连。"""
        limit = int(self.config.get("adapters.max_reconnect_attempts", 10))
        count = 0
        from backend.services.account_setup_service import get_status, is_managed
        for account in await self.repo.list_all():
            setup_status = get_status(account.id)["status"] if is_managed(account) else None
            runtime = self.state.get(account.id)
            completing_login = setup_status == "ready" and runtime and runtime.status in {
                AccountStatus.WAITING_QR, AccountStatus.SCANNING,
            }
            if not account.auto_connect and not completing_login:
                continue
            if setup_status == "idle":
                self.state.mark_offline(account.id)
            if self.state.is_online(account.id):
                continue
            runtime = self.state.get(account.id)
            if runtime and runtime.reconnect_attempts >= limit:
                continue
            try:
                result = await self.poll_login(account.id) if completing_login else await self.reconnect(account.id)
                if result.get("success") or result.get("status") == AccountStatus.ONLINE.value:
                    count += 1
            except Exception:  # noqa: BLE001
                logger.exception("账号巡检重连异常：%s", account.id)
        return count

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _start_receiver(self, adapter: BaseAdapter) -> None:
        if adapter.platform == Platform.WECHAT_CLAWBOT.value or (
            adapter.platform == Platform.QQ_BOT.value and adapter.options.config.get("transport", "websocket") == "websocket"
        ):
            from backend.services.channel_service import start_receiver
            start_receiver(adapter)

    def build_adapter(self, account: BotAccount) -> BaseAdapter:
        if account.platform == Platform.QQ.value and (account.adapter_config or {}).get("managed") is True:
            if not account.adapter_base_url or not account.adapter_token or not account.adapter_config.get("webui_token"):
                raise AppError("请先自动准备 QQ 登录环境", status_code=409, code="LOGIN_PREPARING")
        # 平台 -> 协议端配置段：qq 对应 napcat，wechat 对应 gewechat
        adapter_key, fallback_url = {
            Platform.QQ.value: ("napcat", "http://127.0.0.1:3000"),
            Platform.WECHAT.value: ("gewechat", "http://127.0.0.1:2531/v2/api"),
            Platform.QQ_BOT.value: ("qq_bot", "https://api.bot.qq.com"),
            Platform.WECHAT_CLAWBOT.value: ("clawbot", "https://ilinkai.weixin.qq.com"),
        }[account.platform]
        default_base = str(
            self.config.get(f"adapters.{adapter_key}.base_url", fallback_url)
        )
        options = AdapterOptions.from_account(account, default_base_url=default_base)
        if not options.token:
            options.token = str(self.config.get(f"adapters.{adapter_key}.token", ""))
        adapter_config = dict(account.adapter_config or {})
        if account.platform == Platform.QQ.value:
            for key, default in (("webui_url", "http://127.0.0.1:6099"), ("webui_token", "")):
                adapter_config.setdefault(key, self.config.get(f"adapters.napcat.{key}", default))
        if account.platform == Platform.WECHAT.value:
            adapter_config.setdefault(
                "app_id", str(self.config.get("adapters.gewechat.app_id", ""))
            )
        if account.platform == Platform.WECHAT_CLAWBOT.value:
            adapter_config.setdefault("bot_id", account.account_no or "")
        options.config = adapter_config
        return self.factory.get_or_create(options)

    def _to_dict(self, account: BotAccount) -> dict[str, Any]:
        runtime = self.state.get(account.id)
        status = runtime.status.value if runtime else account.status
        return {
            "id": account.id,
            "name": account.name,
            "platform": account.platform,
            "platform_label": PLATFORM_LABELS.get(account.platform, account.platform),
            "account_type": "bot" if account.platform in {Platform.QQ_BOT.value, Platform.WECHAT_CLAWBOT.value} else "account",
            "account_no": account.account_no,
            "adapter_base_url": account.adapter_base_url,
            "adapter_config": {key: value for key, value in (account.adapter_config or {}).items()
                               if key not in {"webui_token", "bot_token", "app_secret", "credential", "get_updates_buf", "login_uuid"}},
            "has_webui_token": bool((account.adapter_config or {}).get("webui_token")),
            "status": status,
            "status_label": ACCOUNT_STATUS_LABELS.get(status, status),
            "character_id": account.character_id,
            "model_id": account.model_id,
            "memory_library_id": getattr(account, "memory_library_id", None) or account.id,
            "settings": account.settings or {},
            "auto_connect": account.auto_connect,
            "last_online_at": account.last_online_at.isoformat(timespec="seconds")
            if account.last_online_at else None,
            "last_error": account.last_error,
            "runtime": runtime.to_dict() if runtime else None,
            "created_at": account.created_at.isoformat(timespec="seconds"),
        }

    def _clean_payload(self, data: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        allowed = {
            "name", "platform", "account_no", "adapter_base_url", "adapter_token",
            "adapter_config", "character_id", "model_id", "settings", "auto_connect",
            "memory_library_id",
        }
        payload = {key: value for key, value in data.items() if key in allowed}
        if payload.get("memory_library_id") is None:
            payload.pop("memory_library_id", None)
        elif not isinstance(payload["memory_library_id"], str) or len(payload["memory_library_id"]) > 40:
            raise ValidationError("请选择有效的记忆库")
        elif payload["memory_library_id"]:
            payload["memory_library_id"] = payload["memory_library_id"].strip()
            if not payload["memory_library_id"]:
                raise ValidationError("请选择有效的记忆库")
        if creating:
            payload.setdefault("platform", Platform.QQ.value)
            payload.setdefault("adapter_config", {})
            payload.setdefault("settings", {})
            if payload["platform"] in {Platform.QQ.value, Platform.WECHAT_CLAWBOT.value} and not payload.get("name"):
                payload["name"] = PLATFORM_LABELS[payload["platform"]]
            if not payload.get("name"):
                raise ValidationError("账号名称不能为空")
        if "platform" in payload and payload["platform"] not in PLATFORM_LABELS:
            raise ValidationError("请选择支持的账号或机器人接入方式")
        if "adapter_config" in payload and not isinstance(
            payload["adapter_config"], dict
        ):
            raise ValidationError("adapter_config 必须是对象")
        if "settings" in payload and not isinstance(payload["settings"], dict):
            raise ValidationError("settings 必须是对象")
        adapter_config = payload.get("adapter_config", {})
        if "managed" in adapter_config and not isinstance(adapter_config["managed"], bool):
            raise ValidationError("自动配置选项必须为布尔值")
        if adapter_config.get("managed") and payload.get("platform", Platform.QQ.value) != Platform.QQ.value:
            raise ValidationError("当前仅 QQ 个人账号支持自动准备登录环境")
        if creating and payload["platform"] == Platform.QQ.value:
            adapter_config.setdefault("managed", not payload.get("adapter_base_url") and not payload.get("adapter_token")
                                      and not adapter_config.get("webui_url"))
        if creating and (adapter_config.get("managed") or payload["platform"] == Platform.WECHAT_CLAWBOT.value):
            payload["auto_connect"] = False
        if payload.get("platform") in {Platform.QQ_BOT.value, Platform.WECHAT_CLAWBOT.value}:
            payload["settings"] = {**payload.get("settings", {}), "voice": False, "emoji": False}
        if payload.get("platform") == Platform.QQ_BOT.value and payload.get("adapter_config", {}).get("transport", "websocket") not in {"websocket", "webhook"}:
            raise ValidationError("QQ 机器人接收方式只支持长连接或事件回调")
        if "name" in payload:
            if not isinstance(payload["name"], str):
                raise ValidationError("连接名称需要 1–64 个字符")
            payload["name"] = payload["name"].strip()
            if not payload["name"] or len(payload["name"]) > 64:
                raise ValidationError("连接名称需要 1–64 个字符")
        return payload
