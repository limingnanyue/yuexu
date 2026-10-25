"""QQ 官方机器人：OpenAPI、WebSocket 网关、回调验签及群聊/私聊文本。"""

from __future__ import annotations

import asyncio
import re
import time
import json
from urllib.parse import quote
from urllib.parse import urlsplit

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from backend.adapters.base_adapter import BaseAdapter, SendResult
from backend.common.constants import MessageScene, Platform
from backend.common.exceptions import AdapterError, AuthError, ValidationError
from backend.common.message import BotEvent, LoginState, MessageSegment, SenderInfo


class QQBotAdapter(BaseAdapter):
    platform = Platform.QQ_BOT.value

    def __init__(self, options):
        super().__init__(options)
        self._access_token = ""
        self._expires = 0.0
        self._token_lock = asyncio.Lock()
        self._gateway_lock = asyncio.Lock()
        self._socket = None
        self._heartbeat_task = None
        self._heartbeat_ack = True
        self._sequence = None
        self._session_id = ""
        self._pending_events = []

    async def close(self):
        await super().close()
        await self._close_gateway()

    async def _close_gateway(self):
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            await asyncio.gather(self._heartbeat_task, return_exceptions=True)
            self._heartbeat_task = None
        if self._socket:
            await self._socket.close()
            self._socket = None

    async def _frame(self):
        frame = json.loads(await self._socket.recv())
        if not isinstance(frame, dict):
            raise AdapterError("QQ 网关返回了无效事件")
        if frame.get("s") is not None:
            self._sequence = frame["s"]
        if frame.get("op") == 11:
            self._heartbeat_ack = True
        return frame

    async def open_gateway(self):
        async with self._gateway_lock:
            if self._socket:
                return
            gateway = await self._api("GET", "/gateway")
            url = str(gateway.get("url") or "")
            parsed = urlsplit(url)
            if parsed.scheme != "wss" or parsed.username or parsed.password or not (parsed.hostname or "").endswith(".qq.com"):
                raise AdapterError("QQ 返回了不可信的网关地址")
            try:
                self._socket = await connect(url, open_timeout=15, close_timeout=5, ping_interval=None, max_size=1024 * 1024)
                hello = await asyncio.wait_for(self._frame(), timeout=15)
                if hello.get("op") != 10:
                    raise AdapterError("QQ 网关握手失败")
                interval = max(1, float(hello.get("d", {}).get("heartbeat_interval", 45000)) / 1000)
                token = "QQBot " + await self._token()
                if self._session_id:
                    identify = {"op":6,"d":{"token":token,"session_id":self._session_id,"seq":self._sequence}}
                else:
                    identify = {"op":2,"d":{"token":token,"intents":1<<25,"shard":[0,1]}}
                await self._socket.send(json.dumps(identify))
                async with asyncio.timeout(20):
                    while True:
                        event = await self._frame()
                        if event.get("op") == 9:
                            self._session_id = ""
                            raise AdapterError("QQ 网关拒绝连接，请确认机器人有群聊与单聊事件权限")
                        if event.get("t") in {"READY", "RESUMED"}:
                            if event.get("t") == "READY":
                                self._session_id = str(event.get("d", {}).get("session_id") or "")
                            break
                        if event.get("op") == 0:
                            self._pending_events.append(event)
                self._heartbeat_ack = True
                self._heartbeat_task = asyncio.create_task(self._heartbeat(interval), name=f"qq-heartbeat-{self.account_id}")
            except (WebSocketException, OSError, ValueError, TimeoutError, AdapterError) as exc:
                await self._close_gateway()
                if isinstance(exc, AdapterError):
                    raise
                raise AdapterError("QQ 网关连接失败，请检查网络与机器人事件权限") from exc

    async def _heartbeat(self, interval):
        try:
            while True:
                await asyncio.sleep(interval)
                if not self._heartbeat_ack:
                    await self._socket.close()
                    return
                self._heartbeat_ack = False
                await self._socket.send(json.dumps({"op":1,"d":self._sequence}))
        except (WebSocketException, OSError):
            if self._socket:
                await self._socket.close()

    async def receive_events(self):
        await self.open_gateway()
        if self._pending_events:
            events, self._pending_events = self._pending_events, []
            return events
        try:
            while True:
                event = await self._frame()
                if event.get("op") in {7, 9}:
                    if event["op"] == 9:
                        self._session_id = ""
                    raise AdapterError("QQ 网关请求重新连接")
                if event.get("op") == 1:
                    await self._socket.send(json.dumps({"op":1,"d":self._sequence}))
                if event.get("op") == 0:
                    return [event]
        except (WebSocketException, OSError, ValueError, AdapterError) as exc:
            await self._close_gateway()
            raise AdapterError("QQ 网关连接中断，正在尝试恢复会话") from exc

    def _headers(self):
        return {"Content-Type": "application/json"}

    async def _token(self):
        async with self._token_lock:
            if self._access_token and time.monotonic() < self._expires:
                return self._access_token
            app_id = str(self.options.config.get("app_id") or "")
            if not app_id or not self.options.token:
                raise AdapterError("请填写 QQ 机器人 AppID 和 AppSecret")
            data = await self._post("/app/getAppAccessToken", {"appId": app_id, "clientSecret": self.options.token})
            token = data.get("access_token")
            if not token:
                raise AdapterError("QQ 机器人鉴权失败，请检查 AppID 与 AppSecret")
            self._access_token = str(token)
            self._expires = time.monotonic() + max(1, int(data.get("expires_in", 7200)) - 60)
            return self._access_token

    async def _api(self, method, path, body=None):
        token = await self._token()
        try:
            response = await self.client().request(method, path, json=body, headers={"Authorization": f"QQBot {token}"})
            if response.status_code == 401:
                self._expires = 0
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AdapterError("QQ 官方机器人接口调用失败，请检查权限、凭据与网络") from exc
        if not isinstance(data, dict) or data.get("code") not in (None, 0):
            raise AdapterError("QQ 官方机器人：" + str(data.get("message", "请求失败") if isinstance(data, dict) else "返回格式错误"))
        return data

    async def fetch_login_qrcode(self):
        raise AdapterError("QQ 官方机器人使用 AppID / AppSecret 连接，不使用个人账号二维码")

    async def check_login_status(self):
        info = await self.get_self_info()
        return LoginState(status="online", account_no=str(info.get("id") or self.options.config.get("app_id")), nickname=str(info.get("username") or "QQ 机器人"))

    async def get_self_info(self):
        info = await self._api("GET", "/users/@me")
        return {**info, "user_id": info.get("id"), "nickname": info.get("username")}

    def _key(self):
        secret = self.options.token.encode()
        if not secret:
            raise AdapterError("QQ AppSecret 未配置")
        seed = (secret * ((32 + len(secret) - 1) // len(secret)))[:32]
        return Ed25519PrivateKey.from_private_bytes(seed)

    def sign(self, message: bytes) -> str:
        return self._key().sign(message).hex()

    def verify_signature(self, timestamp, body, signature) -> bool:
        try:
            if abs(time.time() - int(timestamp)) > 300:
                return False
            self._key().public_key().verify(bytes.fromhex(signature), timestamp.encode() + body)
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False

    def parse_webhook(self, body, headers):
        try:
            payload = json.loads(body)
        except (ValueError, UnicodeError) as exc:
            raise ValidationError("事件必须为 JSON") from exc
        if not isinstance(payload, dict):
            raise ValidationError("事件格式错误")
        app_id = headers.get("X-Bot-Appid")
        if app_id and app_id != str(self.options.config.get("app_id")):
            raise AuthError("QQ AppID 不匹配")
        if payload.get("op") == 13:
            data = payload.get("d") or {}
            if not isinstance(data, dict):
                raise ValidationError("回调验证格式错误")
            timestamp, token = data.get("event_ts"), data.get("plain_token")
            try:
                valid_time = abs(time.time() - int(timestamp)) <= 300
            except (TypeError, ValueError):
                valid_time = False
            if not valid_time or not isinstance(token, str) or not 1 <= len(token) <= 256:
                raise ValidationError("回调验证已过期或参数不完整")
            return None, {"plain_token": token, "signature": self.sign((str(timestamp) + token).encode())}
        if not self.verify_signature(headers.get("X-Signature-Timestamp", ""), body,
                                     headers.get("X-Signature-Ed25519", "")):
            raise AuthError("QQ 回调签名无效")
        return payload, {"op": 12, "d": 0}

    def parse_event(self, raw, bot_id):
        kind = raw.get("t")
        if raw.get("op") != 0 or kind not in {"C2C_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"}:
            return None
        data = raw.get("d") or {}
        if not isinstance(data, dict):
            return None
        group = str(data.get("group_openid") or "")
        author = data.get("author") or {}
        if not isinstance(author, dict) or author.get("bot"):
            return None
        user = str(author.get("member_openid") or author.get("user_openid") or author.get("id") or "")
        text = re.sub(r"<@!?\d+>\s*", "", str(data.get("content") or "")).strip()
        if not user or not text:
            return None
        return BotEvent(bot_id=bot_id, platform=Platform.QQ_BOT, user_id=user,
                        group_id=group or None, scene=MessageScene.GROUP if group else MessageScene.PRIVATE,
                        message_id=str(data.get("id") or ""), raw_message=text,
                        segments=[MessageSegment.text(text)], sender=SenderInfo(user_id=user),
                        is_at_me=kind == "GROUP_AT_MESSAGE_CREATE", raw=raw)

    async def reply(self, event, payload):
        return await self._send(event.scene, str(event.group_id) if event.is_group else event.user_id, payload, event.message_id)

    async def send_message(self, scene, target_id, payload):
        return await self._send(scene, target_id, payload)

    async def _send(self, scene, target_id, payload, message_id=None):
        # shortcut: 当前对接文本消息，富媒体上传完成后扩展图片和语音。
        if not payload.text:
            return SendResult(success=False, error="QQ 官方机器人当前需要文本消息")
        kind = "groups" if scene == MessageScene.GROUP else "users"
        body = {"content": payload.text, "msg_type": 0}
        if message_id:
            body.update(msg_id=message_id, msg_seq=1)
        data = await self._api("POST", f"/v2/{kind}/{quote(target_id, safe='')}/messages", body)
        return SendResult(success=True, message_id=str(data.get("id") or ""))

    async def get_group_list(self):
        raise AdapterError("QQ 官方机器人不提供普通 QQ 群列表，请使用事件中的群 OpenID")

    async def get_friend_list(self):
        raise AdapterError("QQ 官方机器人不提供个人 QQ 好友列表")
