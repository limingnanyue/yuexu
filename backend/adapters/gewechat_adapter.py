"""Gewechat（微信）适配器：对接 Gewechat HTTP 接口，并归一化为 OneBot11 口径事件。

Gewechat 的接口路径与返回结构随版本变化较大，统一通过账号
``adapter_config.endpoints`` 覆盖，默认值仅作参考。
"""

from __future__ import annotations

from typing import Any

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

logger = get_logger("yuexu.adapter.gewechat")

# checkLogin 瞬态失败（服务抖动 / 网络闪断）的容忍次数：低于阈值保持等待扫码，
# 连续超过阈值才判定离线，避免用户扫码过程中被一次抖动打断。
LOGIN_CHECK_TOLERANCE = 6


class GewechatAdapter(BaseAdapter):
    """微信 / Gewechat 适配器。"""

    platform = Platform.WECHAT.value

    def __init__(self, options) -> None:  # noqa: ANN001
        super().__init__(options)
        self.app_id = str(options.config.get("app_id") or "")
        # uuid 随 options 持久化，后端重启 / 适配器重建后轮询仍能对上原二维码会话。
        self._login_uuid = str(options.config.get("login_uuid") or "") or None
        self._check_failures = 0

    def endpoint(self, key: str, default: str) -> str:
        return str(self.options.config.get("endpoints", {}).get(key, default))

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.options.token:
            headers["X-GEWE-TOKEN"] = self.options.token
        return headers

    def _body(self, **kwargs: Any) -> dict[str, Any]:
        body = {"appId": self.app_id}
        body.update(kwargs)
        return body

    # ------------------------------------------------------------------
    # 登录
    # ------------------------------------------------------------------
    async def fetch_login_qrcode(self) -> LoginQrcode:
        if not self.options.token:
            token = await self._post(self.endpoint("token", "/tools/getTokenId"))
            if token.get("ret") not in (0, 200) or not isinstance(token.get("data"), str):
                raise AdapterError("无法获取 Gewechat Token，请检查服务地址与部署状态")
            self.options.token = token["data"]
            self.client().headers["X-GEWE-TOKEN"] = self.options.token
        data = await self._post(self.endpoint("qrcode", "/login/getLoginQrCode"), self._body(proxyIp=""))
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        if data.get("ret") not in (0, 200, None):
            raise AdapterError(str(data.get("msg") or data.get("message") or "获取微信二维码失败"))
        if payload.get("appId"):
            self.app_id = str(payload["appId"])
            self.options.config["app_id"] = self.app_id
        self._login_uuid = str(payload.get("uuid") or "")
        self.options.config["login_uuid"] = self._login_uuid
        self._check_failures = 0
        qrcode = self._qrcode_from_data(payload)
        if not (qrcode.image_base64 or qrcode.image_url):
            raise AdapterError("Gewechat 未返回二维码：" + str(data.get("message") or ""))
        return qrcode

    async def check_login_status(self) -> LoginState:
        if not self._login_uuid:
            return LoginState(status=AccountStatus.WAITING_QR.value, message="请先获取二维码")
        try:
            data = await self._post(
                self.endpoint("check_login", "/login/checkLogin"),
                self._body(uuid=self._login_uuid),
            )
        except AdapterError as exc:
            self._check_failures += 1
            if self._check_failures < LOGIN_CHECK_TOLERANCE:
                return LoginState(
                    status=AccountStatus.WAITING_QR.value,
                    message=f"Gewechat 连接波动，正在重试（{self._check_failures}/{LOGIN_CHECK_TOLERANCE}）",
                )
            return LoginState(status=AccountStatus.OFFLINE.value, message=str(exc))
        self._check_failures = 0

        payload = data.get("data") or {}
        status_code = payload.get("status")
        info = payload.get("loginInfo") or {}
        if info or (status_code == 2 and payload.get("wxid")):
            return LoginState(
                status=AccountStatus.ONLINE.value, message="已登录",
                account_no=str(info.get("wxid") or payload.get("wxid") or "") or None,
                nickname=str(info.get("nickName") or info.get("nickname") or payload.get("nickname") or "") or None,
            )
        if status_code in (1, 2):
            return LoginState(
                status=AccountStatus.SCANNING.value,
                message="已扫码，请在手机端确认",
                raw=payload,
            )
        return LoginState(status=AccountStatus.WAITING_QR.value, message="等待扫码", raw=payload)

    async def get_self_info(self) -> dict[str, Any]:
        data = await self._post(
            self.endpoint("self_info", "/personal/getProfile"), self._body()
        )
        payload = data.get("data") or {}
        if not payload:
            raise AdapterError(str(data.get("message") or "微信未登录"))
        return {**payload, "nickname": payload.get("nickName") or payload.get("nickname") or ""}

    async def logout(self) -> None:
        try:
            await self._post(self.endpoint("logout", "/login/logout"), self._body())
        except AdapterError as exc:
            logger.warning("Gewechat 下线失败：%s", exc)

    # ------------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------------
    async def send_message(
        self, scene: MessageScene, target_id: str, payload: MessagePayload
    ) -> SendResult:
        sent_any = False
        last: SendResult | None = None
        for segment in payload.segments:
            if segment.type == SegmentType.TEXT.value and segment.content:
                last = await self._send_text(target_id, segment.content)
            elif segment.type in {SegmentType.EMOJI.value, SegmentType.IMAGE.value}:
                file = segment.file_path or segment.url
                if file:
                    last = await self._send_image(target_id, file)
            elif segment.type == SegmentType.VOICE.value:
                file = segment.file_path or segment.url
                if file:
                    last = await self._send_voice(target_id, file)
            if last and not last.success:
                return last
            sent_any = sent_any or bool(last and last.success)
        if not sent_any:
            return SendResult(success=False, error="消息内容为空或平台不支持")
        return last or SendResult(success=True)

    async def _send_text(self, to_wxid: str, content: str) -> SendResult:
        data = await self._post(
            self.endpoint("post_text", "/message/postText"),
            self._body(toWxid=to_wxid, content=content),
        )
        return self._grade_result(data)

    async def _send_image(self, to_wxid: str, file: str) -> SendResult:
        data = await self._post(
            self.endpoint("post_image", "/message/postImage"),
            self._body(toWxid=to_wxid, imgUrl=file),
        )
        return self._grade_result(data)

    async def _send_voice(self, to_wxid: str, file: str) -> SendResult:
        data = await self._post(
            self.endpoint("post_voice", "/message/postVoice"),
            self._body(toWxid=to_wxid, voiceUrl=file),
        )
        return self._grade_result(data)

    @staticmethod
    def _grade_result(data: dict[str, Any]) -> SendResult:
        if data.get("ret") not in (0, 200, None) or data.get("code") not in (0, 200, None):
            return SendResult(
                success=False,
                error=str(data.get("msg") or data.get("message") or "发送失败"),
                raw=data,
            )
        payload = data.get("data") or {}
        return SendResult(
            success=True,
            message_id=str(payload.get("newMsgId") or payload.get("msgId") or ""),
            raw=data,
        )

    # ------------------------------------------------------------------
    # 联系人与群
    # ------------------------------------------------------------------
    async def get_group_list(self) -> list[dict[str, Any]]:
        data = await self._post(
            self.endpoint("group_list", "/group/getChatroomList"), self._body()
        )
        items = data.get("data") or []
        if isinstance(items, dict):
            items = items.get("chatroomList") or items.get("list") or []
        return [
            {
                "group_id": str(item.get("chatroomId") or item.get("wxid") or ""),
                "group_name": item.get("nickName") or item.get("remark") or "",
                "member_count": item.get("memberCount", 0),
            }
            for item in items
            if isinstance(item, dict)
        ]

    async def get_friend_list(self) -> list[dict[str, Any]]:
        data = await self._post(
            self.endpoint("friend_list", "/contacts/fetchContactsList"), self._body()
        )
        items = data.get("data") or []
        if isinstance(items, dict):
            items = items.get("friends") or items.get("list") or []
        return [
            {
                "user_id": str(item.get("userName") or item.get("wxid") or ""),
                "nickname": item.get("nickName") or item.get("remark") or "",
            }
            for item in items
            if isinstance(item, dict)
        ]

    async def mute_member(self, group_id: str, user_id: str, duration: int = 60) -> SendResult:
        endpoint = self.endpoint("mute_member", "")
        if not endpoint:
            return SendResult(success=False, error="Gewechat 当前版本不支持禁言")
        data = await self._post(
            endpoint,
            self._body(chatroomId=group_id, wxid=user_id, duration=duration),
        )
        return self._grade_result(data)

    # ------------------------------------------------------------------
    # 事件归一化（Gewechat 回调）
    # ------------------------------------------------------------------
    def parse_event(self, raw: dict[str, Any], bot_id: str) -> BotEvent | None:
        type_name = str(raw.get("TypeName") or raw.get("type") or "")
        data = raw.get("Data") or raw.get("data") or {}
        if type_name not in {"AddMsg", "addMsg", "message"}:
            return None
        if not isinstance(data, dict):
            return None

        from_user = self._string_field(data, "FromUserName")
        to_user = self._string_field(data, "ToUserName")
        chat_id = str(data.get("ChatroomId") or data.get("chatroomId") or "")
        content = self._string_field(data, "Content")
        msg_type = int(data.get("MsgType") or data.get("msgType") or 1)

        is_group = bool(chat_id) or from_user.endswith("@chatroom")
        group_id = chat_id or (from_user if from_user.endswith("@chatroom") else "")
        user_id = from_user
        if is_group and content.startswith("wxid_"):
            # 群消息格式： "wxid_xxx:\n消息内容"
            head, _, tail = content.partition(":\n")
            if head:
                user_id = head
                content = tail or content
        if content.startswith("<"):
            # XML / 引用消息：提取可读文本
            content = self._extract_readable_xml(content)

        segments = []
        if msg_type in {1, 49} and content:
            from backend.common.message import MessageSegment

            segments.append(MessageSegment.text(content))

        event = BotEvent(
            bot_id=bot_id,
            platform=Platform.WECHAT,
            post_type="message",
            scene=MessageScene.GROUP if is_group else MessageScene.PRIVATE,
            user_id=user_id,
            group_id=group_id or None,
            message_id=str(data.get("MsgId") or data.get("NewMsgId") or ""),
            self_id=to_user,
            segments=segments,
            raw_message=content,
            sender=SenderInfo(user_id=user_id, nickname=""),
            is_at_me=bool(data.get("IsAt") or data.get("isAt")),
            raw=raw,
        )
        return event

    @staticmethod
    def _string_field(data: dict[str, Any], key: str) -> str:
        value = data.get(key)
        if isinstance(value, dict):
            return str(value.get("string") or value.get("String") or "")
        return str(value or "")

    @staticmethod
    def _extract_readable_xml(content: str) -> str:
        """从微信 XML 消息中提取 title / content 文本。"""
        import re

        matches = re.findall(r"<(?:title|content)>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</(?:title|content)>", content, re.S)
        return " ".join(item.strip() for item in matches if item.strip())[:2000]

    @staticmethod
    def to_segments(payload: MessagePayload) -> list[dict[str, Any]]:
        """统一消息段 -> Gewechat 发送描述（主要供日志 / 调试使用）。"""
        result: list[dict[str, Any]] = []
        for segment in payload.segments:
            if segment.type == SegmentType.TEXT.value:
                result.append({"type": "text", "content": segment.content})
            elif segment.type == SegmentType.VOICE.value:
                result.append({"type": "voice", "file": segment.file_path or segment.url})
            elif segment.type in {SegmentType.EMOJI.value, SegmentType.IMAGE.value}:
                result.append({"type": "image", "file": segment.file_path or segment.url})
        return result
