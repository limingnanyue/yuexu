"""受管 NapCat：Windows 原生组件，Linux 独立容器，共用账号配置。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import socket
import stat
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

import httpx

from backend.common.exceptions import AppError
from backend.core.config_loader import get_config
from backend.services.component_download import download_component

VERSION = "v4.18.41"
RELEASE_URL = f"https://github.com/NapNeko/NapCatQQ/releases/download/{VERSION}/NapCat.Shell.Windows.Node.zip"
RELEASE_SHA256 = "51fbb10e7bcd56b0c2a6de86c37811e7518330e48a137ac689ab1e4d8627d3f0"

# shortcut: 原生数据路径适配仅验证过固定发行包，升级版本时必须重新验证隔离与登录。
BOOTSTRAP = r"""'use strict';
const fs = require('node:fs');
const path = require('node:path');
const entry = process.env.NAPCAT_MANAGED_ENTRY;
const home = path.resolve(process.env.NAPCAT_MANAGED_HOME);
const expectedWrapper = path.resolve(path.dirname(entry), 'wrapper.node');
fs.mkdirSync(home, {recursive: true});
const dlopen = process.dlopen;
process.dlopen = function (module, filename, ...args) {
  const result = dlopen.call(this, module, filename, ...args);
  if (path.resolve(filename) === expectedWrapper) {
    const original = module.exports.NodeQQNTWrapperUtil;
    if (!original || typeof original.getNTUserDataInfoConfig !== 'function') {
      throw new Error('Managed QQ data isolation unavailable');
    }
    const isolated = Object.create(original);
    Object.defineProperty(isolated, 'getNTUserDataInfoConfig', {value: () => home});
    module.exports.NodeQQNTWrapperUtil = isolated;
    if (module.exports.NodeQQNTWrapperUtil !== isolated ||
        module.exports.NodeQQNTWrapperUtil.getNTUserDataInfoConfig() !== home) {
      throw new Error('Managed QQ data isolation failed');
    }
  }
  return result;
};
require(entry);
"""


class NapCatRuntime:
    def __init__(self, config=None):
        self._config = config
        self._processes: dict[str, subprocess.Popen] = {}
        self._credentials: dict[str, dict] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._install_lock = asyncio.Lock()
        self._docker = None

    @property
    def config(self):
        return self._config or get_config()

    @property
    def root(self) -> Path:
        return self.config.resolve_path(self.config.get("paths.data_dir", "data")) / "adapters" / "napcat"

    def _account_dir(self, account_id: str) -> Path:
        if not isinstance(account_id, str) or not re.fullmatch(r"acc_[A-Za-z0-9_-]{1,100}", account_id):
            raise AppError("账号标识无效，无法准备登录环境")
        directory = self.root / account_id
        if directory.resolve().parent != self.root.resolve():
            raise AppError("账号数据目录不安全")
        return directory

    @staticmethod
    def _write_json(path: Path, data: dict) -> None:
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
        temporary.replace(path)

    def _configure(self, account_id: str, directory: Path) -> dict:
        directory.mkdir(parents=True, exist_ok=True)
        config_dir = directory / "config"
        config_dir.mkdir(exist_ok=True)
        manifest = directory / "managed.json"
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text("utf-8"))
                valid_ports = all(type(data[key]) is int and 1024 <= data[key] <= 65535 for key in ("port", "webui_port"))
                valid_tokens = all(isinstance(data[key], str) and re.fullmatch(r"[0-9a-f]{64}", data[key]) for key in ("token", "webui_token"))
                if not valid_ports or not valid_tokens or data["port"] == data["webui_port"]:
                    raise ValueError("Invalid managed manifest")
            except (ValueError, KeyError, TypeError) as exc:
                raise AppError("账号登录环境配置损坏，请保留数据并联系管理员") from exc
        else:
            # 同时绑定两个端口，避免操作系统立即复用刚释放的端口。
            with socket.socket() as onebot, socket.socket() as webui:
                onebot.bind(("127.0.0.1", 0))
                webui.bind(("127.0.0.1", 0))
                data = {"port": onebot.getsockname()[1], "webui_port": webui.getsockname()[1],
                        "token": secrets.token_hex(32), "webui_token": secrets.token_hex(32)}
            self._write_json(manifest, data)
        self._write_json(config_dir / "webui.json", {
            "host": "127.0.0.1", "port": data["webui_port"], "token": data["webui_token"],
            "disableWebUI": False, "autoLoginAccount": "", "enableXForwardedFor": False,
        })
        onebot = {"network": {
            "httpServers": [{"name": "yuexu-api", "enable": True, "host": "127.0.0.1", "port": data["port"],
                             "token": data["token"], "enableCors": False, "enableWebsocket": False, "messagePostFormat": "array"}],
            "httpClients": [{"name": "yuexu-events", "enable": True, "token": data["token"], "messagePostFormat": "array",
                             "url": f"http://127.0.0.1:{int(self.config.get('app.port', 8000))}/api/bot/managed/{account_id}",
                             "reportSelfMessage": False}],
        }}
        self._write_json(config_dir / "onebot11.json", onebot)
        for path in config_dir.glob("onebot11_*.json"):
            if re.fullmatch(r"onebot11_[0-9]+\.json", path.name):
                self._write_json(path, onebot)
        return {"adapter_base_url": f"http://127.0.0.1:{data['port']}", "adapter_token": data["token"],
                "adapter_config": {"managed": True, "webui_url": f"http://127.0.0.1:{data['webui_port']}",
                                   "webui_token": data["webui_token"]}}

    async def _download(self, client: httpx.AsyncClient, archive: Path, expected: str, report=None) -> None:
        urls = self.config.get("adapters.napcat.download_urls", [])
        if not isinstance(urls, list) or any(not isinstance(url, str) for url in urls):
            raise AppError("组件下载源配置需要为 HTTPS 地址列表")
        await download_component(client, [url for url in urls if url] + [RELEASE_URL], archive, expected, report)

    @staticmethod
    def _extract(archive: zipfile.ZipFile, target: Path) -> None:
        members = archive.infolist()
        if len(members) > 20000 or sum(item.file_size for item in members) > 2 * 1024 ** 3:
            raise AppError("登录环境安装包大小异常")
        for item in members:
            name = item.filename.replace("\\", "/")
            parts = PurePosixPath(name).parts
            if (not parts or name.startswith("/") or any(part in {".", ".."} or ":" in part or part.rstrip(" .") != part for part in parts)
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise AppError("登录环境安装包包含不安全路径")
            if (target / name).resolve().is_relative_to(target.resolve()) is False:
                raise AppError("登录环境安装包路径越界")
        for item in members:
            destination = target / item.filename.replace("\\", "/")
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)

    async def _prepare(self, report=None) -> Path:
        directory = self.root / "runtime" / VERSION
        async with self._install_lock:
            marker = directory / ".ready"
            required = ("node.exe", "index.js", "wrapper.node", "napcat/napcat.mjs")
            if (marker.exists() and marker.read_text("utf-8") == RELEASE_SHA256
                    and all((directory / name).is_file() for name in required)):
                return directory
            directory.parent.mkdir(parents=True, exist_ok=True)
            archive = directory.parent / f"{VERSION}.zip"
            staging = directory.with_name(VERSION + ".installing")
            if any(path.resolve().parent != directory.parent.resolve() for path in (directory, staging)):
                raise AppError("QQ 登录环境安装目录不安全")
            try:
                if report:
                    report("downloading", "首次使用正在下载 QQ 登录环境（约 124 MB）")
                offline = self.config.get("adapters.napcat.offline_archive", "")
                if offline:
                    source = self.config.resolve_path(offline)
                    if not source.is_file():
                        raise AppError("配置的离线组件包不存在，请检查 offline_archive 路径")
                    with source.open("rb") as handle:
                        digest = await asyncio.to_thread(hashlib.file_digest, handle, "sha256")
                    if digest.hexdigest() != RELEASE_SHA256:
                        raise AppError("离线组件包校验失败，请使用指定版本的官方完整包")
                    if source.resolve() != archive.resolve():
                        temporary = archive.with_suffix(".import")
                        try:
                            await asyncio.to_thread(shutil.copyfile, source, temporary)
                            temporary.replace(archive)
                        finally:
                            temporary.unlink(missing_ok=True)
                async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(60, read=120)) as client:
                    await self._download(client, archive, RELEASE_SHA256, report)
                if report:
                    report("configuring", "正在校验并安装 QQ 登录环境")
                if staging.exists():
                    await asyncio.to_thread(shutil.rmtree, staging)
                with zipfile.ZipFile(archive) as package:
                    await asyncio.to_thread(self._extract, package, staging)
                for name in required:
                    if not (staging / name).is_file():
                        raise AppError("登录环境安装包缺少运行文件")
                (staging / ".ready").write_text(RELEASE_SHA256, "utf-8")
                if directory.exists():
                    await asyncio.to_thread(shutil.rmtree, directory)
                staging.replace(directory)
            except httpx.HTTPError as exc:
                raise AppError("下载 QQ 登录环境失败，请检查网络后重试") from exc
            finally:
                if staging.exists():
                    await asyncio.to_thread(shutil.rmtree, staging)
        return directory

    def _start(self, binary: Path, directory: Path, account_no: str | None = None) -> subprocess.Popen:
        ports = json.loads((directory / "managed.json").read_text("utf-8"))
        try:
            for key in ("port", "webui_port"):
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", ports[key]))
        except OSError as exc:
            raise AppError("QQ 登录环境端口已被占用，请关闭遗留的登录环境后重试") from exc
        bootstrap = directory / "managed.cjs"
        bootstrap.write_text(BOOTSTRAP, "utf-8")
        temporary = directory / "temp"
        temporary.mkdir(exist_ok=True)
        env = {**os.environ, "NAPCAT_WORKDIR": str(directory.resolve()),
               "NAPCAT_MANAGED_HOME": str((directory / "qq").resolve()),
               "NAPCAT_MANAGED_ENTRY": str((binary / "index.js").resolve()),
               "TEMP": str(temporary.resolve()), "TMP": str(temporary.resolve()),
               "NAPCAT_DISABLE_MULTI_PROCESS": "1", "NAPCAT_DISABLE_MULTIPROCESSING": "1"}
        command = [str((binary / "node.exe").resolve()), str(bootstrap.resolve())]
        if account_no and re.fullmatch(r"[0-9]+", account_no):
            command.extend(["-q", account_no])
        with (directory / "runtime.log").open("ab") as log:
            return subprocess.Popen(command, cwd=binary, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))

    async def _wait_ready(self, process: subprocess.Popen, credentials: dict) -> None:
        token = credentials["adapter_config"]["webui_token"]
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            for _ in range(90):
                if process.poll() is not None:
                    raise AppError("QQ 登录环境启动失败，请查看账号目录的 runtime.log")
                try:
                    response = await client.post(credentials["adapter_config"]["webui_url"] + "/api/auth/login", json={
                        "hash": hashlib.sha256((token + ".napcat").encode()).hexdigest(),
                    })
                    data = response.json()
                    if response.is_success and data.get("code") == 0 and data.get("data", {}).get("Credential"):
                        return
                except (httpx.HTTPError, ValueError, AttributeError):
                    pass
                await asyncio.sleep(1)
        raise AppError("QQ 登录环境启动超时，请重试；详情见账号目录的 runtime.log")

    async def ensure(self, account_id: str, report=None, *, account_no: str | None = None) -> dict:
        directory = self._account_dir(account_id)
        mode = self.config.get("adapters.napcat.runtime", "auto")
        system = platform.system()
        if mode not in {"auto", "native", "docker"}:
            raise AppError("QQ 登录环境运行方式只支持 auto、native 或 docker")
        if system == "Linux" and mode in {"auto", "docker"}:
            async with self._locks.setdefault(account_id, asyncio.Lock()):
                if self._docker is None:
                    from backend.services.napcat_docker import NapCatDockerRuntime
                    self._docker = NapCatDockerRuntime(self.config)
                credentials = self._configure(account_id, directory)
                return await self._docker.ensure(account_id, directory, credentials, report, account_no=account_no)
        if system != "Windows" or mode == "docker" or platform.machine().lower() not in {"amd64", "x86_64"}:
            raise AppError("自动环境支持 Windows x64 原生运行或 Linux Docker，请检查运行方式")
        async with self._locks.setdefault(account_id, asyncio.Lock()):
            process = self._processes.get(account_id)
            if process is not None and process.poll() is None:
                return self._credentials[account_id]
            binary = await self._prepare(report)
            credentials = self._configure(account_id, directory)
            if report:
                report("starting", "配置已完成，正在启动 QQ 登录环境")
            process = self._start(binary, directory, account_no)
            self._processes[account_id] = process
            self._credentials[account_id] = credentials
            try:
                await self._wait_ready(process, credentials)
                return credentials
            except BaseException:
                await self._stop(account_id)
                raise

    async def _stop(self, account_id: str) -> None:
        process = self._processes.pop(account_id, None)
        self._credentials.pop(account_id, None)
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            await asyncio.to_thread(process.wait, timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            await asyncio.to_thread(process.wait, timeout=5)
        except ProcessLookupError:
            pass

    async def stop(self, account_id: str) -> None:
        self._account_dir(account_id)
        async with self._locks.setdefault(account_id, asyncio.Lock()):
            if self._docker is None and platform.system() == "Linux" and (self.root / ".docker-owner").is_file():
                from backend.services.napcat_docker import NapCatDockerRuntime
                self._docker = NapCatDockerRuntime(self.config)
            if self._docker is not None:
                await self._docker.stop(account_id)
            await self._stop(account_id)

    def is_running(self, account_id: str) -> bool:
        process = self._processes.get(account_id)
        return (process is not None and process.poll() is None) or (self._docker is not None and self._docker.is_running(account_id))

    async def close(self) -> None:
        await asyncio.gather(*(self.stop(account_id) for account_id in list(self._processes)))
        if self._docker is not None:
            await self._docker.close()


napcat_runtime = NapCatRuntime()
