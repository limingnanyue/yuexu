"""适配器抽象基类：隔离 QQ / 微信协议差异，上层只面向统一消息结构。

新增平台只需继承 ``BaseAdapter`` 并在 ``adapter_factory`` 注册，
业务层（分发、推送、群管）无需改动。
"""

from __future__ import annotations

import base64
import asyncio
from io import BytesIO
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from backend.common.constants import MessageScene, Platform, SegmentType
from backend.common.exceptions import AdapterError
from backend.common.logger import get_logger
from backend.common.message import (
    BotEvent,
    LoginQrcode,
    LoginState,
    MessagePayload,
)

logger = get_logger("yuexu.adapter")


@dataclass
class AdapterOptions:
    """适配器连接参数（由账号表组装）。"""

    account_id: str
    platform: str = Platform.QQ.value
    base_url: str = "http://127.0.0.1:3000"
    token: str = ""
    timeout: float = 15.0
    config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_account(cls, account: Any, default_base_url: str = "") -> "AdapterOptions":
        adapter_config = getattr(account, "adapter_config", None) or {}
        return cls(
            account_id=account.id,
            platform=account.platform,
            base_url=(account.adapter_base_url or default_base_url).rstrip("/"),
            token=account.adapter_token or "",
            timeout=float(adapter_config.get("timeout", 15)),
            config=adapter_config,
        )


@dataclass
class SendResult:
    """发送结果。"""

    success: bool
    message_id: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class BaseAdapter(ABC):
    """平台适配器抽象基类。"""

    platform: str = Platform.QQ.value

    def __init__(self, options: AdapterOptions) -> None:
        self.options = options
        self.account_id = options.account_id
        self._client: httpx.AsyncClient | None = None
        self.receive_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    # HTTP 客户端
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.options.token:
            headers["Authorization"] = f"Bearer {self.options.token}"
        return headers

    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.options.base_url,
                timeout=self.options.timeout,
                headers=self._headers(),
            )
        return self._client

    async def close(self) -> None:
        if self.receive_task is not None:
            self.receive_task.cancel()
            await asyncio.gather(self.receive_task, return_exceptions=True)
            self.receive_task = None
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = await self.client().post(path, json=payload or {})
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise AdapterError(f"接口未返回 JSON 对象：{path}")
            return data
        except httpx.TimeoutException as exc:
            raise AdapterError(f"请求超时：{path}") from exc
        except httpx.HTTPError as exc:
            raise AdapterError(f"请求失败：{path}（{exc}）") from exc
        except ValueError as exc:
            raise AdapterError(f"响应不是合法 JSON：{path}") from exc

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = await self.client().get(path, params=params or {})
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise AdapterError(f"接口未返回 JSON 对象：{path}")
            return data
        except httpx.TimeoutException as exc:
            raise AdapterError(f"请求超时：{path}") from exc
        except httpx.HTTPError as exc:
            raise AdapterError(f"请求失败：{path}（{exc}）") from exc
        except ValueError as exc:
            raise AdapterError(f"响应不是合法 JSON：{path}") from exc

    # ------------------------------------------------------------------
    # 登录相关
    # ------------------------------------------------------------------
    @abstractmethod
    async def fetch_login_qrcode(self) -> LoginQrcode:
        """获取登录二维码。"""

    @abstractmethod
    async def check_login_status(self) -> LoginState:
        """查询扫码 / 登录状态。"""

    @abstractmethod
    async def get_self_info(self) -> dict[str, Any]:
        """获取机器人自身账号信息。"""

    async def logout(self) -> None:
        """主动下线（默认无操作，子类按平台实现）。"""

    # ------------------------------------------------------------------
    # 消息发送
    # ------------------------------------------------------------------
    @abstractmethod
    async def send_message(
        self, scene: MessageScene, target_id: str, payload: MessagePayload
    ) -> SendResult:
        """发送一条统一消息。"""

    async def send_private(self, user_id: str, payload: MessagePayload) -> SendResult:
        return await self.send_message(MessageScene.PRIVATE, user_id, payload)

    async def send_group(self, group_id: str, payload: MessagePayload) -> SendResult:
        return await self.send_message(MessageScene.GROUP, group_id, payload)

    async def reply(self, event: BotEvent, payload: MessagePayload) -> SendResult:
        """按事件场景回复。"""
        if event.is_group:
            return await self.send_group(str(event.group_id), payload)
        return await self.send_private(event.user_id, payload)

    # ------------------------------------------------------------------
    # 群组 / 联系人
    # ------------------------------------------------------------------
    @abstractmethod
    async def get_group_list(self) -> list[dict[str, Any]]:
        """获取群列表。"""

    @abstractmethod
    async def get_friend_list(self) -> list[dict[str, Any]]:
        """获取好友列表。"""

    async def mute_member(self, group_id: str, user_id: str, duration: int = 60) -> SendResult:
        """禁言成员（秒），具体平台子类实现。"""
        return SendResult(success=False, error="当前适配器不支持禁言")

    async def kick_member(self, group_id: str, user_id: str) -> SendResult:
        """移出群成员。"""
        return SendResult(success=False, error="当前适配器不支持踢人")

    # ------------------------------------------------------------------
    # 事件解析
    # ------------------------------------------------------------------
    @abstractmethod
    def parse_event(self, raw: dict[str, Any], bot_id: str) -> BotEvent | None:
        """把平台原始上报事件归一化为 ``BotEvent``。"""

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _onebot_segments_to_unified(message: Any) -> list[Any]:
        """OneBot11 消息段 -> 统一消息段。"""
        from backend.common.message import MessageSegment

        segments: list[Any] = []
        if isinstance(message, str):
            return [MessageSegment.text(message)] if message else []
        for item in message or []:
            if not isinstance(item, dict):
                continue
            seg_type = item.get("type")
            data = item.get("data") or {}
            if seg_type == "text":
                text = str(data.get("text", ""))
                if text:
                    segments.append(MessageSegment.text(text))
            elif seg_type in {"image", "mface"}:
                file = data.get("file")
                url = data.get("url") or (file if isinstance(file, str) and file.startswith(("http://", "https://")) else None)
                segments.append(
                    MessageSegment(type=SegmentType.IMAGE.value, file_path=file, url=url, data=data)
                )
            elif seg_type == "record":
                segments.append(MessageSegment.voice(str(data.get("file", ""))))
            elif seg_type == "face":
                segments.append(
                    MessageSegment(
                        type=SegmentType.FACE.value,
                        content=str(data.get("summary") or data.get("name") or "") or None,
                        data={**data, "id": str(data.get("id", ""))},
                    )
                )
            elif seg_type == "at":
                segments.append(
                    MessageSegment(type=SegmentType.AT.value, data={"user_id": str(data.get("qq", ""))})
                )
            elif seg_type == "reply":
                segments.append(
                    MessageSegment(type=SegmentType.REPLY.value, data={"id": str(data.get("id", ""))})
                )
        return segments

    @staticmethod
    def _detect_at_me(segments: list[Any], self_id: str) -> bool:
        return any(
            segment.type == SegmentType.AT.value
            and str(segment.data.get("user_id", "")) == str(self_id)
            for segment in segments
        )

    @staticmethod
    def _qrcode_from_data(data: dict[str, Any]) -> LoginQrcode:
        """兼容 base64 / url / 文件路径三种二维码返回格式。"""
        qr_text = data.get("qrcode_text")
        if not qr_text and isinstance(data.get("qrcode"), str) and data["qrcode"].startswith(("http://", "https://", "weixin://")):
            qr_text = data["qrcode"]
        if qr_text:
            import qrcode
            from qrcode.image.svg import SvgPathImage

            buffer = BytesIO()
            try:
                qrcode.make(str(qr_text), image_factory=SvgPathImage, border=4).save(buffer)
            except qrcode.exceptions.DataOverflowError as exc:
                raise AdapterError("平台返回的二维码内容过长，请重新获取") from exc
            return LoginQrcode(
                qrcode_id=str(data.get("qrcode_id") or data.get("uuid") or ""),
                image_base64="data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode(),
                raw={},
            )
        image_base64 = (
            data.get("qrcode") or data.get("qrCode") or data.get("base64")
            or data.get("qrcode_base64") or data.get("qrImg")
        )
        image_url = data.get("url") or data.get("qrcode_url") or data.get("qrUrl")
        if isinstance(image_base64, str) and image_base64.startswith("http"):
            image_url, image_base64 = image_base64, None
        qrcode = LoginQrcode(
            qrcode_id=str(data.get("qrcode_id") or data.get("uuid") or data.get("qrcodeId") or ""),
            image_base64=image_base64 if image_base64 else None,
            image_url=image_url,
            expires_in=int(data.get("expires_in") or data.get("expire") or 120),
            raw=data,
        )
        return qrcode

    @staticmethod
    def decode_image_base64(value: str | None) -> bytes | None:
        if not value:
            return None
        try:
            payload = value.split(",", 1)[-1]
            return base64.b64decode(payload)
        except (ValueError, TypeError):
            return None
