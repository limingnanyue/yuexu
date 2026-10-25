"""微信 ClawBot / iLink：扫码、验证码、长轮询和隔离会话的文本回复。"""

from __future__ import annotations

import base64
import secrets
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from backend.adapters.base_adapter import BaseAdapter, SendResult
from backend.common.constants import AccountStatus, MessageScene, Platform
from backend.common.exceptions import AdapterError
from backend.common.message import BotEvent, LoginQrcode, LoginState, MessagePayload, MessageSegment, SenderInfo


class ClawBotAdapter(BaseAdapter):
    platform = Platform.WECHAT_CLAWBOT.value

    def __init__(self, options):
        super().__init__(options)
        self._qr_token = ""
        self._contexts: dict[str, str] = {}
        self._cursor = str(options.config.get("get_updates_buf") or "")

    def _headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def set_api_base(self, url: str) -> None:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port not in (None, 443) or not host.endswith(".weixin.qq.com"):
            raise AdapterError("ClawBot 返回了不可信的接入地址，已停止登录")
        self.options.base_url = url.rstrip("/")
        if self._client:
            self._client.base_url = self.options.base_url + "/"

    async def _request(self, method, path, payload=None, *, auth=True, params=None, timeout=40):
        headers = {"iLink-App-Id": "bot", "iLink-App-ClientVersion": "132106"}
        body = dict(payload or {})
        if method == "POST":
            headers.update({
                "AuthorizationType": "ilink_bot_token",
                "X-WECHAT-UIN": base64.b64encode(str(secrets.randbits(32)).encode()).decode(),
            })
            if auth:
                headers["Authorization"] = f"Bearer {self.options.token}"
                body["base_info"] = {"channel_version": "2.4.10", "bot_agent": "Yuexu/0.1.0"}
        try:
            response = await self.client().request(method, path, json=body if method == "POST" else None, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            if path.endswith("getupdates"):
                return {"msgs": []}
            raise AdapterError("ClawBot 请求超时，请重试") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise AdapterError("无法连接微信 ClawBot，请检查网络后重试") from exc
        if not isinstance(data, dict):
            raise AdapterError("微信 ClawBot 返回格式不正确")
        codes = (data.get("ret"), data.get("errcode"))
        if -14 in codes:
            self.options.token = ""
            raise AdapterError("ClawBot 登录已过期，请重新扫码")
        if any(code not in (None, 0) for code in codes):
            raise AdapterError("ClawBot：" + str(data.get("errmsg") or "接口调用失败"))
        return data

    async def fetch_login_qrcode(self) -> LoginQrcode:
        data = await self._request("POST", "/ilink/bot/get_bot_qrcode", {"local_token_list": []}, auth=False, params={"bot_type": "3"})
        self._qr_token = str(data.get("qrcode") or "")
        content = data.get("qrcode_img_content")
        if not self._qr_token or not content:
            raise AdapterError("微信没有返回有效二维码，请重试")
        if str(content).startswith("data:image/"):
            return LoginQrcode(qrcode_id=self._qr_token, image_base64=content)
        return self._qrcode_from_data({"qrcode_text": content, "qrcode_id": self._qr_token})

    async def check_login_status(self, verify_code=None) -> LoginState:
        if not self._qr_token:
            return LoginState(status="waiting_qr", message="请先获取二维码")
        qr_token = self._qr_token
        params = {"qrcode": qr_token}
        if verify_code:
            params["verify_code"] = verify_code
        data = await self._request("GET", "/ilink/bot/get_qrcode_status", auth=False, params=params)
        if qr_token != self._qr_token:
            if not self._qr_token and self.options.token:
                return LoginState(status="online", account_no=self.options.config.get("bot_id"))
            return LoginState(status="waiting_qr" if self._qr_token else "offline", message="请使用最新二维码")
        status = data.get("status")
        if status == "confirmed":
            token, bot_id = data.get("bot_token"), data.get("ilink_bot_id")
            if not token or not bot_id:
                raise AdapterError("微信确认登录后未返回完整凭据，请重新扫码")
            if data.get("baseurl"):
                self.set_api_base(str(data["baseurl"]))
            self.options.token = str(token)
            self.options.config.update(bot_id=str(bot_id), ilink_user_id=str(data.get("ilink_user_id") or ""))
            self._qr_token = ""
            return LoginState(status="online", account_no=str(bot_id), message="ClawBot 已连接")
        if status == "scaned_but_redirect":
            self.set_api_base("https://" + str(data.get("redirect_host") or ""))
            return LoginState(status="scanning", message="已扫码，正在切换微信接入节点")
        if status in {"expired", "verify_code_blocked"}:
            return LoginState(status="error", message="二维码已失效，请点击刷新二维码")
        if status == "need_verifycode":
            return LoginState(status="scanning", message="请输入手机微信上显示的验证码", raw={"needs_verify_code": True})
        if status == "binded_redirect":
            return LoginState(status="error", message="该 ClawBot 已绑定其他实例，请在微信中解除旧绑定后重试")
        return LoginState(status="scanning" if status == "scaned" else "waiting_qr", message="已扫码，请在微信中确认" if status == "scaned" else "等待微信扫码")

    async def get_self_info(self) -> dict[str, Any]:
        if not self.options.token:
            raise AdapterError("ClawBot 尚未登录，请先扫码")
        user_id = self.options.config.get("ilink_user_id")
        if not user_id:
            raise AdapterError("ClawBot 登录资料不完整，请重新扫码")
        await self._request("POST", "/ilink/bot/getconfig", {"ilink_user_id": user_id}, timeout=15)
        return {"user_id": self.options.config.get("bot_id", ""), "nickname": "微信 ClawBot"}

    async def logout(self):
        self._qr_token = ""
        self.options.token = ""

    async def receive_events(self) -> list[dict[str, Any]]:
        data = await self._request("POST", "/ilink/bot/getupdates", {"get_updates_buf": self._cursor})
        if data.get("get_updates_buf"):
            self._cursor = str(data["get_updates_buf"])
            self.options.config["get_updates_buf"] = self._cursor
        messages = data.get("msgs") or []
        return [item for item in messages if isinstance(item, dict)]

    def parse_event(self, raw, bot_id) -> BotEvent | None:
        user = str(raw.get("from_user_id") or "")
        if raw.get("message_type") != 1 or not user or raw.get("group_id"):
            return None
        text = "".join(
            str(item.get("text_item", {}).get("text") or item.get("voice_item", {}).get("text") or "")
            for item in raw.get("item_list", []) if isinstance(item, dict)
        ).strip()
        if not text:
            return None
        context = str(raw.get("context_token") or "")
        if context:
            self._contexts[user] = context
            if len(self._contexts) > 1000:
                self._contexts.pop(next(iter(self._contexts)))
        return BotEvent(bot_id=bot_id, platform=Platform.WECHAT_CLAWBOT, user_id=user,
                        self_id=str(raw.get("to_user_id") or ""), message_id=str(raw.get("message_id") or ""),
                        segments=[MessageSegment.text(text)], raw_message=text,
                        sender=SenderInfo(user_id=user), raw=raw)

    async def reply(self, event, payload) -> SendResult:
        return await self._send_text(event.user_id, payload, str(event.raw.get("context_token") or ""))

    async def send_message(self, scene, target_id, payload) -> SendResult:
        if scene == MessageScene.GROUP:
            return SendResult(success=False, error="ClawBot 当前仅支持微信私聊")
        return await self._send_text(target_id, payload, self._contexts.get(target_id, ""))

    async def _send_text(self, target_id, payload, context) -> SendResult:
        # shortcut: 当前发送文本，接入微信媒体上传和加解密后再扩展图片及语音。
        if not payload.text or not context:
            return SendResult(success=False, error="ClawBot 需要有效的会话上下文与文本；请让该用户先发一条消息")
        data = await self._request("POST", "/ilink/bot/sendmessage", {"msg": {
            "from_user_id": "", "to_user_id": target_id, "client_id": uuid4().hex,
            "message_type": 2, "message_state": 2, "context_token": context,
            "item_list": [{"type": 1, "text_item": {"text": payload.text}}],
        }}, timeout=15)
        return SendResult(success=True, message_id=str(data.get("message_id") or ""))

    async def get_group_list(self):
        raise AdapterError("ClawBot 不提供微信群列表")

    async def get_friend_list(self):
        raise AdapterError("ClawBot 不提供微信通讯录")
