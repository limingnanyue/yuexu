"""NapCat（QQ）适配器：对接 OneBot11 HTTP 接口。

NapCat 以 OneBot11 协议对外提供 HTTP / WS 服务，本适配器负责：
- 扫码登录（独立 WebUI 的 ``/api/QQLogin/GetQQLoginQrcode``）
- 私聊 / 群聊消息发送（文字、图片表情、语音）
- 群列表、好友列表、禁言、踢人
- OneBot11 事件归一化

注意：NapCat 不同版本接口存在差异，可在账号 ``adapter_config`` 中覆盖端点。
"""

from __future__ import annotations

from typing import Any
import base64
import hashlib
from pathlib import Path
import time

import httpx

from backend.adapters.base_adapter import BaseAdapter, SendResult
from backend.common.constants import AccountStatus, MessageScene, Platform, SegmentType
from backend.common.exceptions import AdapterError
from backend.common.logger import get_logger
from backend.common.message import (
    BotEvent,
    LoginQrcode,
    LoginState,
    MessagePayload,
    SenderInfo,
)

logger = get_logger("yuexu.adapter.napcat")


class NapCatAdapter(BaseAdapter):
    """QQ / NapCat OneBot11 适配器。"""

    platform = Platform.QQ.value

    def __init__(self, options) -> None:
        super().__init__(options)
        self._webui_client: httpx.AsyncClient | None = None
        self._webui_credential = ""
        self._webui_expires = 0.0

    async def close(self) -> None:
        await super().close()
        if self._webui_client and not self._webui_client.is_closed:
            await self._webui_client.aclose()

    async def _webui_post(self, path: str, payload=None, *, retry=True) -> dict[str, Any]:
        if not self._webui_client or self._webui_client.is_closed:
            self._webui_client = httpx.AsyncClient(
                base_url=str(self.options.config.get("webui_url") or "http://127.0.0.1:6099").rstrip("/"),
                timeout=self.options.timeout,
            )
        try:
            if time.monotonic() >= self._webui_expires:
                token = str(self.options.config.get("webui_token") or "")
                if not token:
                    raise AdapterError("请填写 NapCat WebUI Token；它与 OneBot Token 是两个不同的配置")
                response = await self._webui_client.post("/api/auth/login", json={
                    "hash": hashlib.sha256((token + ".napcat").encode()).hexdigest(),
                })
                response.raise_for_status()
                auth = response.json()
                data = auth.get("data") or {}
                if data.get("require2FA"):
                    raise AdapterError("NapCat WebUI 已启用双重验证，请先在 NapCat WebUI 中完成扫码登录，再连接账号")
                credential = data.get("Credential")
                if auth.get("code") != 0 or not credential:
                    raise AdapterError("NapCat WebUI 登录失败，请检查 WebUI Token")
                self._webui_credential = str(credential)
                self._webui_expires = time.monotonic() + 3300
            response = await self._webui_client.post(path, json=payload or {}, headers={
                "Authorization": f"Bearer {self._webui_credential}",
            })
            response.raise_for_status()
            result = response.json()
            if result.get("code") != 0:
                message = str(result.get("message") or result.get("msg") or "请求失败")
                if retry and "uthoriz" in message:
                    self._webui_expires = 0
                    return await self._webui_post(path, payload, retry=False)
                raise AdapterError("NapCat WebUI：" + message)
            return result.get("data") or {}
        except httpx.HTTPError as exc:
            raise AdapterError("无法连接 NapCat WebUI，请先启动 NapCat，并检查 WebUI 地址（通常为 6099 端口）") from exc
        except (ValueError, AttributeError) as exc:
            raise AdapterError("NapCat WebUI 返回格式不正确，请确认填写的是 NapCat 管理地址") from exc

    # ------------------------------------------------------------------
    # 端点
    # ------------------------------------------------------------------
    def endpoint(self, key: str, default: str) -> str:
        return str(self.options.config.get("endpoints", {}).get(key, default))

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------
    async def fetch_login_qrcode(self) -> LoginQrcode:
        if self.options.config.get("endpoints", {}).get("qrcode"):
            data = await self._post(self.endpoint("qrcode", "/get_qrcode"), {})
            payload = data.get("data") if isinstance(data.get("data"), dict) else data
        else:
            payload = await self._webui_post("/api/QQLogin/GetQQLoginQrcode")
        qrcode = self._qrcode_from_data(payload or {})
        if not (qrcode.image_base64 or qrcode.image_url or qrcode.file_path):
            raise AdapterError("NapCat 未返回二维码，请确认服务已启动或改用 WebUI 扫码")
        logger.info("已获取 QQ 登录二维码：%s", self.account_id)
        return qrcode

    async def refresh_login_qrcode(self) -> LoginQrcode:
        data = await self._webui_post("/api/QQLogin/RefreshQRcode")
        if data.get("restarting"):
            raise AdapterError("QQ 登录服务正在重启，请稍后重新获取二维码")
        # NapCat 刷新接口直接返回新二维码链接（qrcodeurl），无需再走一次获取接口。
        refreshed = str(data.get("qrcodeurl") or data.get("qrcode") or "")
        if refreshed:
            qrcode = self._qrcode_from_data({"qrcode": refreshed})
            if qrcode.image_base64 or qrcode.image_url:
                return qrcode
        return await self.fetch_login_qrcode()

    async def check_login_status(self) -> LoginState:
        try:
            info = await self.get_self_info()
        except AdapterError as exc:
            if not self.options.config.get("webui_token"):
                return LoginState(status=AccountStatus.OFFLINE.value, message=str(exc))
            data = await self._webui_post("/api/QQLogin/CheckLoginStatus")
            if data.get("loginError"):
                return LoginState(status=AccountStatus.ERROR.value, message=str(data["loginError"]))
            if data.get("isOffline"):
                return LoginState(
                    status=AccountStatus.ERROR.value,
                    message="QQ 已下线（可能在其他设备登录），请重新扫码",
                )
            if data.get("isLogin"):
                # 登录已成功但 OneBot 通道尚未就绪，继续轮询等待初始化完成。
                return LoginState(status=AccountStatus.SCANNING.value, message="登录成功，正在初始化消息通道")
            accepted = bool(data.get("qrLoginAccepted")) or data.get("loginPhase") in {"qrcode_scanned", "initializing"}
            return LoginState(
                status=AccountStatus.SCANNING.value if accepted else AccountStatus.WAITING_QR.value,
                message="QQ 正在初始化，请稍候" if accepted else "等待扫码并在手机上确认",
            )
        account_no = str(info.get("user_id") or "")
        if not account_no:
            return LoginState(status=AccountStatus.WAITING_QR.value)
        return LoginState(
            status=AccountStatus.ONLINE.value,
            message="已登录",
            account_no=account_no,
            nickname=str(info.get("nickname") or ""),
            raw=info,
        )

    async def get_self_info(self) -> dict[str, Any]:
        data = await self._post(self.endpoint("login_info", "/get_login_info"))
        info = data.get("data") or {}
        if not info or data.get("retcode") not in (0, None) or data.get("status") == "failed":
            raise AdapterError(str(data.get("wording") or data.get("message") or "未登录"))
        return info

    async def logout(self) -> None:
        try:
            await self._post(self.endpoint("logout", "/logout"), {})
        except AdapterError as exc:
            logger.warning("NapCat 下线失败：%s", exc)

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------
    async def send_message(
        self, scene: MessageScene, target_id: str, payload: MessagePayload
    ) -> SendResult:
        message = self.to_onebot_segments(payload)
        if not message:
            return SendResult(success=False, error="消息内容为空")

        if scene == MessageScene.GROUP:
            path = self.endpoint("send_group", "/send_group_msg")
            body = {"group_id": self._as_id(target_id), "message": message}
        else:
            path = self.endpoint("send_private", "/send_private_msg")
            body = {"user_id": self._as_id(target_id), "message": message}

        data = await self._post(path, body)
        if data.get("status") == "failed" or data.get("retcode") not in (0, None):
            message = str(data.get("wording") or data.get("message") or "发送失败")
            return SendResult(success=False, error=message, raw=data)
        result = data.get("data") or {}
        return SendResult(
            success=True,
            message_id=str(result.get("message_id") or ""),
            raw=data,
        )

    async def get_group_list(self) -> list[dict[str, Any]]:
        data = await self._post(self.endpoint("group_list", "/get_group_list"))
        groups = data.get("data") or []
        return [
            {
                "group_id": str(item.get("group_id", "")),
                "group_name": item.get("group_name", ""),
                "member_count": item.get("member_count", 0),
            }
            for item in groups
            if item.get("group_id")
        ]

    async def get_friend_list(self) -> list[dict[str, Any]]:
        data = await self._post(self.endpoint("friend_list", "/get_friend_list"))
        friends = data.get("data") or []
        return [
            {
                "user_id": str(item.get("user_id", "")),
                "nickname": item.get("nickname") or item.get("remark") or "",
            }
            for item in friends
            if item.get("user_id")
        ]

    async def mute_member(self, group_id: str, user_id: str, duration: int = 60) -> SendResult:
        data = await self._post(
            self.endpoint("set_group_ban", "/set_group_ban"),
            {
                "group_id": self._as_id(group_id),
                "user_id": self._as_id(user_id),
                "duration": max(0, int(duration)),
            },
        )
        return self._bool_result(data, "禁言失败")

    async def kick_member(self, group_id: str, user_id: str) -> SendResult:
        data = await self._post(
            self.endpoint("set_group_kick", "/set_group_kick"),
            {
                "group_id": self._as_id(group_id),
                "user_id": self._as_id(user_id),
                "reject_add_request": False,
            },
        )
        return self._bool_result(data, "踢人失败")

    # ------------------------------------------------------------------
    # 事件归一化
    # ------------------------------------------------------------------
    def parse_event(self, raw: dict[str, Any], bot_id: str) -> BotEvent | None:
        post_type = raw.get("post_type")
        self_id = str(raw.get("self_id") or "")
        if post_type == "message_sent":
            return None
        if post_type == "meta_event":
            return BotEvent(
                bot_id=bot_id,
                platform=Platform.QQ,
                post_type="meta_event",
                sub_type=raw.get("meta_event_type"),
                self_id=self_id,
                raw=raw,
            )
        if post_type == "message":
            message_type = raw.get("message_type", "private")
            is_group = message_type == "group"
            sender = raw.get("sender") or {}
            segments = self._onebot_segments_to_unified(raw.get("message"))
            event = BotEvent(
                bot_id=bot_id,
                platform=Platform.QQ,
                post_type="message",
                sub_type=raw.get("sub_type"),
                scene=MessageScene.GROUP if is_group else MessageScene.PRIVATE,
                user_id=str(raw.get("user_id") or sender.get("user_id") or ""),
                group_id=str(raw["group_id"]) if is_group and raw.get("group_id") else None,
                message_id=str(raw.get("message_id") or ""),
                self_id=self_id,
                segments=segments,
                raw_message=str(raw.get("raw_message") or ""),
                sender=SenderInfo(
                    user_id=str(raw.get("user_id") or sender.get("user_id") or ""),
                    nickname=str(sender.get("nickname") or ""),
                    card=str(sender.get("card") or ""),
                    role=str(sender.get("role") or "member"),
                ),
                is_at_me=self._detect_at_me(segments, self_id),
                timestamp=int(raw.get("time") or 0),
                raw=raw,
            )
            return event
        if post_type == "notice":
            return BotEvent(
                bot_id=bot_id,
                platform=Platform.QQ,
                post_type="notice",
                sub_type=raw.get("notice_type") or raw.get("sub_type"),
                scene=MessageScene.GROUP if raw.get("group_id") else MessageScene.PRIVATE,
                group_id=str(raw["group_id"]) if raw.get("group_id") else None,
                user_id=str(raw.get("user_id") or ""),
                operator_id=str(raw.get("operator_id") or ""),
                target_id=str(raw.get("target_id") or ""),
                self_id=self_id,
                timestamp=int(raw.get("time") or 0),
                raw=raw,
            )
        if post_type == "request":
            return BotEvent(
                bot_id=bot_id,
                platform=Platform.QQ,
                post_type="request",
                sub_type=raw.get("request_type"),
                user_id=str(raw.get("user_id") or ""),
                group_id=str(raw["group_id"]) if raw.get("group_id") else None,
                self_id=self_id,
                raw=raw,
            )
        logger.debug("忽略未知 NapCat 事件：%s", post_type)
        return None

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _as_id(value: str | int) -> int | str:
        """OneBot 接口通常要求数字 ID，非数字时原样传入。"""
        text = str(value)
        return int(text) if text.isdigit() else text

    @staticmethod
    def _bool_result(data: dict[str, Any], default_error: str) -> SendResult:
        if data.get("status") == "failed" or data.get("retcode") not in (0, None):
            return SendResult(
                success=False,
                error=str(data.get("wording") or data.get("message") or default_error),
                raw=data,
            )
        return SendResult(success=True, raw=data)

    @classmethod
    def to_onebot_segments(cls, payload: MessagePayload) -> list[dict[str, Any]]:
        """统一消息段 -> OneBot11 消息段。"""
        segments: list[dict[str, Any]] = []
        for segment in payload.segments:
            if segment.type == SegmentType.TEXT.value and segment.content:
                segments.append({"type": "text", "data": {"text": segment.content}})
            elif segment.type in {SegmentType.EMOJI.value, SegmentType.IMAGE.value, SegmentType.VOICE.value}:
                file = segment.file_path or segment.url
                if file:
                    # NapCat 可能运行在另一台主机或容器，传文件内容避免依赖共享目录。
                    if segment.file_path and Path(file).is_file():
                        try:
                            file = "base64://" + base64.b64encode(Path(file).read_bytes()).decode("ascii")
                        except OSError as exc:
                            raise AdapterError("无法读取待发送的媒体文件") from exc
                    kind = "record" if segment.type == SegmentType.VOICE.value else "image"
                    segments.append({"type": kind, "data": {"file": file}})
                elif segment.type == SegmentType.EMOJI.value:
                    logger.warning("表情缺少文件路径，跳过：%s", segment.emoji_key)
            elif segment.type == SegmentType.AT.value:
                segments.append(
                    {"type": "at", "data": {"qq": segment.data.get("user_id", "")}}
                )
            elif segment.type == SegmentType.REPLY.value:
                segments.append({"type": "reply", "data": {"id": segment.data.get("id", "")}})
        return segments
