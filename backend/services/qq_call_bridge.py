"""KoishiRTC 原生 QQ 控制桥与月叙音频入口的本机连接器，仅接听私聊音频。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
import re
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator
from websockets.asyncio.client import connect

logger = logging.getLogger("yuexu.qq_call_bridge")


class QQCallBridgeSettings(BaseModel):
    account_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    qq_number: str = Field(pattern=r"^[1-9][0-9]{4,19}$")
    control_url: str = "http://127.0.0.1:6110"
    host_url: str = "http://127.0.0.1:6111"
    control_token_file: Path
    yuexu_url: str = "ws://127.0.0.1:8000"
    yuexu_token_file: Path
    input_device: str = Field(min_length=1)
    output_device: str = Field(min_length=1)
    native_input_device: str = Field(min_length=1)
    native_output_device: str = Field(min_length=1)
    host_api: Literal["Windows WASAPI"] = "Windows WASAPI"

    @field_validator("control_url", "host_url", "yuexu_url")
    @classmethod
    def loopback_url(cls, value, info):
        url = httpx.URL(value)
        scheme = "ws" if info.field_name == "yuexu_url" else "http"
        if (url.scheme != scheme or url.host not in {"127.0.0.1", "localhost", "::1"}
                or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}):
            raise ValueError("通话连接只支持不含凭据和参数的本机地址")
        return value.rstrip("/")

    @model_validator(mode="after")
    def separate_native_buses(self):
        buses = [re.sub(r"\b(?:input|output)\b", "", name.lower()).strip()
                 for name in (self.native_input_device, self.native_output_device)]
        if buses[0] == buses[1] or any(not name.strip() or re.search(r"\b(default|primary sound|mapper)\b", name, re.I)
                                     for name in (self.native_input_device, self.native_output_device)):
            raise ValueError("原生音频必须指定两条独立虚拟线路，不能使用默认设备")
        return self


class QQCallBridge:
    def __init__(self, settings: QQCallBridgeSettings):
        self.settings = settings

    def identity(self, state):
        if str(state.get("selfId")) != self.settings.qq_number or not state.get("bootId"):
            raise ValueError("原生桥登录账号不匹配或尚未就绪")
        host = state.get("host") or {}
        if (host.get("ready") is not True or not host.get("bootId")
                or not (host.get("routeReady") is True or (host.get("audioRouting") or {}).get("ready") is True)):
            raise ValueError("原生桥尚未确认两条独立虚拟音频线路")
        self.confirm_route(host.get("audioRouting") or {})

    def confirm_route(self, route):
        selection = route.get("selection") or {}
        if route.get("ready") is not True or any(
            (selection.get(direction) or {}).get("name") != name
            or type((selection.get(direction) or {}).get("id")) is not int or selection[direction]["id"] <= 0
            for direction, name in (("input", self.settings.native_input_device), ("output", self.settings.native_output_device))
        ):
            raise ValueError("原生音频路由未确认或与指定设备不匹配")

    def route_idle(self, state):
        host = state.get("host") or {}
        if (str(state.get("selfId")) != self.settings.qq_number or not state.get("bootId")
                or host.get("ready") is not True or not host.get("bootId")
                or (state.get("call") is not None and state["call"].get("phase") != "ended")):
            raise ValueError("只有匹配账号、原生桥就绪且无通话时可以配置路由")

    async def configure_route(self, client, state):
        host = state.get("host") or {}
        if host.get("routeReady") is True or (host.get("audioRouting") or {}).get("ready") is True:
            self.identity(state)
            return
        self.route_idle(state)
        prefix = self.settings.host_url
        actual = await self.request(client, prefix + "/v1/status")
        if actual.get("bootId") != host["bootId"] or actual.get("ready") is not True:
            raise ValueError("原生 Host 在配置路由前重启或尚未就绪")
        if actual.get("routeReady") is True or (actual.get("audioRouting") or {}).get("ready") is True:
            self.confirm_route(actual.get("audioRouting") or {})
            return
        devices = (await self.request(client, prefix + "/v1/audio/devices")).get("devices")
        if not isinstance(devices, list):
            raise ValueError("原生设备枚举无效")
        selection = {}
        for direction, name in (("input", self.settings.native_input_device), ("output", self.settings.native_output_device)):
            matches = [device for device in devices if isinstance(device, dict) and device.get("direction") == direction
                       and device.get("name") == name]
            if len(matches) != 1 or type(matches[0].get("id")) is not int or matches[0]["id"] <= 0:
                raise ValueError("原生虚拟设备缺失、默认或名称不唯一")
            selection[direction] = {"id": matches[0]["id"], "name": name}
        current = await self.request(client, "/v1/status")
        self.route_idle(current)
        if current["bootId"] != state["bootId"] or current["host"]["bootId"] != host["bootId"]:
            raise ValueError("原生桥在枚举设备期间重启")
        if current["host"].get("routeReady") is True or (current["host"].get("audioRouting") or {}).get("ready") is True:
            self.identity(current)
            return
        confirmed = await self.request(client, prefix + "/v1/audio/route", selection)
        self.confirm_route(confirmed)
        if confirmed["selection"] != selection:
            raise ValueError("原生桥确认的设备 ID 与本次枚举不符")

    def incoming(self, state):
        self.identity(state)
        call = state.get("call") or {}
        if (call.get("kind") == "private" and call.get("direction") == "incoming"
                and call.get("phase") == "ringing" and call.get("media") == "audio"
                and call.get("acceptReady") is True and re.fullmatch(r"[1-9][0-9]{4,19}", str(call.get("callerUin", "")))
                and state.get("capabilities", {}).get("private.accept", {}).get("status") == "supported"):
            return call
        return None

    def devices(self, audio):
        apis = audio.query_hostapis()
        devices = audio.query_devices()
        indexes = []
        for name, direction in ((self.settings.input_device, "input"), (self.settings.output_device, "output")):
            matches = [i for i, device in enumerate(devices) if device["name"] == name
                       and apis[device["hostapi"]]["name"] == self.settings.host_api
                       and device[f"max_{direction}_channels"] > 0]
            if len(matches) != 1:
                raise ValueError("指定的虚拟音频端点缺失或名称不唯一，请重新枚举")
            indexes.append(matches[0])
        bus_names = [re.sub(r"\b(?:input|output)\b", "", name.lower()).strip()
                     for name in (self.settings.input_device, self.settings.output_device)]
        if indexes[0] == indexes[1] or bus_names[0] == bus_names[1]:
            raise ValueError("收音和发音必须使用两条独立线路")
        return tuple(indexes)

    async def request(self, client, path, body=None):
        is_host = path.startswith(self.settings.host_url + "/")
        response = await client.request("POST" if body is not None else "GET", path, json=body, timeout=20 if is_host else 4)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
            raise ValueError("原生通话控制请求失败")
        success = type(result.get("code")) is int and result["code"] == 0 if is_host else result.get("ok") is True
        if not success:
            raise ValueError("原生通话控制请求失败")
        return result["data"]

    async def submit_audio_start(self, client, boot_id, call_id, caller):
        state = await self.request(client, "/v1/status")
        self.identity(state)
        call = state.get("call") or {}
        peer_field = {"incoming": "callerUin", "outgoing": "peerUin"}.get(call.get("direction"))
        profile = (state.get("host") or {}).get("nativeProfile") or {}
        if (state["bootId"] != boot_id or call.get("id") != call_id or call.get("phase") != "connected"
                or call.get("kind") != "private" or call.get("media") != "audio" or not peer_field
                or str(call.get(peer_field)) != str(caller) or profile.get("id") != "qq-win32-9.9.36-53644-x64"):
            raise ValueError("只能为匹配的已接通 Windows 私聊语音提交音频启动")
        host_boot_id = state["host"]["bootId"]
        request_id = "audio-" + call_id
        receipt = await self.request(client, self.settings.host_url + "/v1/invoke", {
            "command": 18, "params": [True, True], "requestId": request_id,
        })
        if (receipt.get("posted") is not True or type(receipt.get("command")) is not int or receipt["command"] != 18
                or type(receipt.get("id")) is not int or receipt["id"] <= 0):
            raise ValueError("原生音频启动未确认提交")
        try:
            async with asyncio.timeout(3):
                while True:
                    host = await self.request(client, self.settings.host_url + "/v1/status")
                    ack = host.get("nativeAudioStart")
                    if (host.get("bootId") != host_boot_id or not isinstance(ack, dict)
                            or ack.get("requestId") != request_id or type(ack.get("nativeId")) is not int
                            or ack["nativeId"] != receipt["id"] or ack.get("posted") is not True):
                        raise ValueError("原生音频启动确认不匹配或 Host 已重启")
                    if ack.get("resultCode") is None and ack.get("receivedAt") is None:
                        await asyncio.sleep(.1)
                        continue
                    if (type(ack.get("resultCode")) is not int or not isinstance(ack.get("receivedAt"), str)
                            or not ack["receivedAt"]):
                        raise ValueError("原生音频启动确认无效")
                    if ack["resultCode"] != 0:
                        raise ValueError(f"原生音频启动失败（错误码 {ack['resultCode']}）")
                    break
        except TimeoutError as exc:
            raise ValueError("原生音频启动确认超时") from exc
        current = await self.request(client, "/v1/status")
        self.identity(current)
        confirmed = current.get("call") or {}
        if (current["bootId"] != boot_id or current["host"]["bootId"] != host_boot_id
                or confirmed.get("id") != call_id or confirmed.get("phase") != "connected"
                or any(confirmed.get(key) != call.get(key) for key in ("kind", "direction", "media", peer_field))):
            raise ValueError("原生音频启动期间通话已变化")
        return receipt

    async def answer(self, client, state):
        call = self.incoming(state)
        if call is None:
            return
        boot_id, call_id, caller = state["bootId"], call["id"], call["callerUin"]
        try:
            await self.request(client, "/v1/calls/accept", {"callId": call_id, "requestId": uuid4().hex})
            async with asyncio.timeout(30):
                while True:
                    current = await self.request(client, "/v1/status")
                    self.identity(current)
                    native = current.get("call") or {}
                    if current["bootId"] != boot_id or native.get("id") != call_id or native.get("phase") in {"ended", "error"}:
                        return
                    if native.get("phase") == "connected":
                        break
                    await asyncio.sleep(0.25)
            logger.info("QQ 来电已接通")
            await self.relay(client, boot_id, call_id, caller)
        finally:
            try:
                current = await self.request(client, "/v1/status")
                if (current.get("bootId") == boot_id and (current.get("call") or {}).get("id") == call_id
                        and current["call"].get("phase") != "ended"):
                    await self.request(client, "/v1/calls/hangup", {"callId": call_id, "requestId": uuid4().hex})
            except Exception:
                logger.warning("未确认原生通话已结束，请检查通话状态")

    async def relay(self, client, boot_id, call_id, caller):
        import sounddevice as audio

        await self.submit_audio_start(client, boot_id, call_id, caller)
        input_id, output_id = self.devices(audio)
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue(maxsize=25)
        failure = asyncio.Event()

        def enqueue(pcm, bad):
            if bad or queue.full():
                failure.set()
            else:
                queue.put_nowait(pcm)

        def capture(data, frames, timing, status):
            loop.call_soon_threadsafe(enqueue, bytes(data), bool(status))

        async def monitor():
            while True:
                await asyncio.sleep(0.25)
                state = await self.request(client, "/v1/status")
                self.identity(state)
                native = state.get("call") or {}
                if state["bootId"] != boot_id or native.get("id") != call_id or native.get("phase") != "connected":
                    return

        token = self.settings.yuexu_token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("月叙通话凭据为空")
        address = f"{self.settings.yuexu_url}/api/voice-call/ws/{self.settings.account_id}/{caller}"
        async with connect(address, additional_headers={"Authorization": f"Bearer {token}"}, max_size=64000) as websocket:
            ready = json.loads(await asyncio.wait_for(websocket.recv(), 5))
            if (ready.get("type") != "ready" or ready.get("sample_rate") != 16000
                    or ready.get("encoding") != "pcm_s16le" or ready.get("channels") != 1):
                raise ValueError("月叙通话音频格式不匹配")
            conversion = audio.WasapiSettings(auto_convert=True)
            with audio.RawInputStream(device=input_id, samplerate=16000, channels=1, dtype="int16", blocksize=320,
                                      extra_settings=conversion, callback=capture), \
                 audio.RawOutputStream(device=output_id, samplerate=16000, channels=1, dtype="int16", blocksize=320,
                                       extra_settings=conversion) as output:
                async def uplink():
                    while True:
                        await websocket.send(await queue.get())

                async def downlink():
                    async for message in websocket:
                        if isinstance(message, bytes):
                            if len(message) % 2:
                                raise ValueError("下行音频样本不完整")
                            # 等待 ASR/LLM 时输出故意留空，首次写入的欠载标志不代表设备故障。
                            await asyncio.to_thread(output.write, message)
                        elif json.loads(message).get("type") == "error":
                            logger.warning("月叙通话处理失败，请检查服务日志")

                tasks = [asyncio.create_task(coro) for coro in (uplink(), downlink(), monitor(), failure.wait())]
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                    if failure.is_set():
                        raise ValueError("虚拟音频采集异常或队列已满")
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self):
        import sounddevice as audio

        self.devices(audio)
        token = self.settings.control_token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise ValueError("原生桥凭据为空")
        last_invite = None
        last_error = None
        async with httpx.AsyncClient(base_url=self.settings.control_url, headers={"Authorization": f"Bearer {token}"},
                                     timeout=4, trust_env=False, follow_redirects=False) as client:
            while True:
                try:
                    state = await self.request(client, "/v1/status")
                    capabilities = await self.request(client, "/v1/capabilities")
                    if capabilities.get("bootId") != state.get("bootId") or capabilities.get("selfId") != state.get("selfId"):
                        raise ValueError("原生桥在读取状态期间重启")
                    state["capabilities"] = capabilities.get("capabilities", {})
                    await self.configure_route(client, state)
                    call = self.incoming(state)
                    if call and (state["bootId"], call["id"]) != last_invite:
                        last_invite = state["bootId"], call["id"]
                        await self.answer(client, state)
                    last_error = None
                except Exception as exc:
                    error = type(exc).__name__
                    if error != last_error:
                        logger.warning("通话桥暂不可用（%s），等待本机服务就绪", error)
                    last_error = error
                await asyncio.sleep(0.5)


def main():
    parser = argparse.ArgumentParser(description="连接 QQ 原生通话桥与月叙")
    parser.add_argument("config", type=Path)
    arguments = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = QQCallBridgeSettings.model_validate_json(arguments.config.read_text(encoding="utf-8"))
    asyncio.run(QQCallBridge(settings).run())


if __name__ == "__main__":
    main()
