"""Linux 受管 NapCat：通过本机 Docker Engine 管理各账号的独立容器与数据卷。"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import tarfile
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from backend.common.exceptions import AppError

IMAGE = 'mlikiowa/napcat-docker:v4.18.41@sha256:b101b8968cc31ae428ec0f8e117386e4ced7773b2d8226ed9f7ddfcec55f1b7e'
OWNER = 'io.yuexu.napcat.owner'
ACCOUNT = 'io.yuexu.napcat.account'
SPEC = 'io.yuexu.napcat.spec'
START = r'''for f in /app/napcat/config/onebot11_[0-9]*.json; do
  [ -f "$f" ] || continue
  n=${f##*/onebot11_}; n=${n%.json}
  case "$n" in *[!0-9]*) continue;; esac
  cp /app/napcat/config/onebot11.json "$f" || exit 1
done
exec bash /app/entrypoint.sh'''
logger = logging.getLogger(__name__)


class NapCatDockerRuntime:
    def __init__(self, config):
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._version = None
        self._owner = None
        self._containers: dict[str, str] = {}
        self._running: dict[str, bool] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._image_lock = asyncio.Lock()
        self._monitor_task: asyncio.Task | None = None

    @property
    def root(self) -> Path:
        return self.config.resolve_path(self.config.get('paths.data_dir', 'data')) / 'adapters' / 'napcat'

    @staticmethod
    def _validate_account(account_id: str) -> None:
        if not isinstance(account_id, str) or not re.fullmatch(r'acc_[A-Za-z0-9_-]{1,100}', account_id):
            raise AppError('账号标识无效，无法准备服务器登录环境')

    def _identity(self) -> str:
        if self._owner is None:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.root / '.docker-owner'
            try:
                with path.open('x', encoding='ascii') as handle:
                    handle.write(uuid.uuid4().hex)
            except FileExistsError:
                pass
            owner = path.read_text('ascii').strip()
            if not re.fullmatch(r'[a-f0-9]{32}', owner):
                raise AppError('服务器登录环境归属文件损坏，请保留账号数据并联系管理员')
            self._owner = owner
        return self._owner

    def _name(self, account_id: str) -> str:
        self._validate_account(account_id)
        return f'yuexu-napcat-{self._identity()[:12]}-{account_id}'

    def _check_owner(self, data: dict, account_id: str, *, volume=False) -> None:
        labels = data.get('Labels', {}) if volume else data.get('Config', {}).get('Labels', {})
        if not isinstance(labels, dict) or labels.get(OWNER) != self._identity() or labels.get(ACCOUNT) != account_id:
            raise AppError('同名 Docker 资源不属于当前月叙实例，已停止操作，请联系管理员')

    async def _request(self, method: str, path: str, *, missing=False, **kwargs) -> httpx.Response:
        try:
            if self._client is None:
                socket = self.config.get('adapters.napcat.docker.socket', '/var/run/docker.sock')
                self._client = httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=socket), base_url='http://docker',
                                               trust_env=False, timeout=httpx.Timeout(120, connect=5))
            if self._version is None:
                response = await self._client.get('/version')
                response.raise_for_status()
                version = response.json().get('ApiVersion')
                if not isinstance(version, str) or not re.fullmatch(r'1\.\d+', version):
                    raise ValueError('Invalid Docker API version')
                self._version = version
            response = await self._client.request(method, f'/v{self._version}{path}', **kwargs)
            if not (missing and response.status_code == 404):
                response.raise_for_status()
            return response
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise AppError('无法连接 Docker Engine，请确认 Docker 已启动且月叙有权访问 Docker socket') from exc

    async def _inspect(self, name: str, account_id: str) -> dict | None:
        response = await self._request('GET', f'/containers/{name}/json', missing=True)
        if response.status_code == 404:
            return None
        data = response.json()
        self._check_owner(data, account_id)
        return data

    async def _prepare_image(self, image: str, report=None) -> None:
        async with self._image_lock:
            response = await self._request('GET', f'/images/{quote(image, safe="")}/json', missing=True)
            if response.status_code != 404:
                return
            reference, _, digest = image.partition('@')
            colon = reference.rfind(':')
            tagged = colon > reference.rfind('/')
            repository = reference[:colon] if tagged else reference
            tag = digest or (reference[colon + 1:] if tagged else 'latest')
            for attempt in range(3):
                if report:
                    report('downloading', f'正在拉取服务器 QQ 登录镜像（首次约 600 MB，第 {attempt + 1}/3 次）')
                try:
                    async with self._client.stream('POST', f'/v{self._version}/images/create', params={'fromImage': repository, 'tag': tag},
                                                   timeout=httpx.Timeout(180, connect=10)) as response:
                        response.raise_for_status()
                        async for line in response.aiter_lines():
                            if not line.strip():
                                continue
                            data = json.loads(line)
                            if data.get('error') or data.get('errorDetail'):
                                raise ValueError('Docker image pull failed')
                            progress = data.get('progressDetail') or {}
                            current, total = progress.get('current', 0), progress.get('total', 0)
                            if report and isinstance(current, int) and isinstance(total, int) and total > 0:
                                report('downloading', f'正在拉取服务器 QQ 登录镜像：当前层 {min(100, current * 100 // total)}%')
                    return
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    if attempt == 2:
                        raise AppError('服务器 QQ 镜像拉取失败。可配置 Docker 镜像加速或代理，或用 docker load 导入离线镜像后重试') from exc
                    await asyncio.sleep(attempt + 1)

    async def _volumes(self, name: str, account_id: str) -> list[dict]:
        mounts = []
        for role, target in (('config', '/app/napcat/config'), ('qq', '/app/.config/QQ'), ('plugins', '/app/napcat/plugins')):
            source = f'{name}-{role}'
            response = await self._request('GET', f'/volumes/{source}', missing=True)
            if response.status_code == 404:
                response = await self._request('POST', '/volumes/create', json={
                    'Name': source, 'Labels': {OWNER: self._identity(), ACCOUNT: account_id},
                })
            self._check_owner(response.json(), account_id, volume=True)
            mounts.append({'Type': 'volume', 'Source': source, 'Target': target})
        return mounts

    @staticmethod
    def _archive(directory: Path) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            for name in ('webui.json', 'onebot11.json'):
                content = (directory / 'config' / name).read_bytes()
                info = tarfile.TarInfo(name)
                info.size, info.mode = len(content), 0o600
                archive.addfile(info, io.BytesIO(content))
        return buffer.getvalue()

    async def _wait_ready(self, name: str, account_id: str, credentials: dict) -> None:
        token = credentials['adapter_config']['webui_token']
        async with httpx.AsyncClient(timeout=2, trust_env=False) as client:
            for _ in range(90):
                container = await self._inspect(name, account_id)
                if not container or not container.get('State', {}).get('Running'):
                    raise AppError('服务器 QQ 登录环境已退出，请查看对应 NapCat 容器日志')
                try:
                    response = await client.post(credentials['adapter_config']['webui_url'] + '/api/auth/login', json={
                        'hash': hashlib.sha256((token + '.napcat').encode()).hexdigest(),
                    })
                    data = response.json()
                    if response.is_success and data.get('code') == 0 and data.get('data', {}).get('Credential'):
                        return
                except (httpx.HTTPError, ValueError, AttributeError):
                    pass
                await asyncio.sleep(1)
        raise AppError('服务器 QQ 登录环境启动超时，请重试并查看对应 NapCat 容器日志')

    async def ensure(self, account_id: str, directory: Path, credentials: dict, report=None, *, account_no=None) -> dict:
        name = self._name(account_id)
        if directory.resolve() != (self.root / account_id).resolve():
            raise AppError('账号登录环境目录不安全')
        async with self._locks.setdefault(account_id, asyncio.Lock()):
            image = self.config.get('adapters.napcat.docker.image', IMAGE)
            if not isinstance(image, str) or not image.strip() or any(c.isspace() for c in image):
                raise AppError('服务器 QQ 登录镜像配置无效')
            archive = self._archive(directory)
            account_no = account_no if isinstance(account_no, str) and re.fullmatch(r'[0-9]+', account_no) else ''
            fingerprint = hashlib.sha256(archive + image.encode() + account_no.encode() + START.encode()).hexdigest()
            current = await self._inspect(name, account_id)
            await self._prepare_image(image, report)
            mounts = await self._volumes(name, account_id)
            self._containers[account_id] = name
            try:
                if current and current['Config']['Labels'].get(SPEC) != fingerprint:
                    await self._stop(account_id)
                    await self._request('DELETE', f'/containers/{name}')
                    current = None
                if current is None:
                    await self._request('POST', '/containers/create', params={'name': name}, json={
                        'Image': image, 'Hostname': f'yuexu-{account_id}', 'WorkingDir': '/app',
                        'Env': [f'ACCOUNT={account_no}'], 'Entrypoint': ['/bin/sh', '-c', START],
                        'Labels': {OWNER: self._identity(), ACCOUNT: account_id, SPEC: fingerprint},
                        'HostConfig': {'NetworkMode': 'host', 'Mounts': mounts, 'RestartPolicy': {'Name': 'unless-stopped'},
                                       'LogConfig': {'Type': 'json-file', 'Config': {'max-size': '10m', 'max-file': '3'}}},
                    })
                if current is None or not current.get('State', {}).get('Running'):
                    if report:
                        report('configuring', '正在配置服务器 QQ 登录环境')
                    await self._request('PUT', f'/containers/{name}/archive', params={'path': '/app/napcat/config'},
                                        content=archive, headers={'Content-Type': 'application/x-tar'})
                    if report:
                        report('starting', '正在启动服务器 QQ 登录环境')
                    await self._request('POST', f'/containers/{name}/start')
                await self._wait_ready(name, account_id, credentials)
                self._running[account_id] = True
                if self._monitor_task is None or self._monitor_task.done():
                    self._monitor_task = asyncio.create_task(self._monitor())
                return credentials
            except BaseException:
                try:
                    await asyncio.shield(self._stop(account_id))
                except Exception:
                    logger.warning('停止未就绪的 NapCat 容器失败：%s', account_id)
                raise

    async def _stop(self, account_id: str) -> None:
        name = self._containers.get(account_id)
        if name is None and (self.root / '.docker-owner').is_file():
            name = self._name(account_id)
            self._containers[account_id] = name
        if name:
            container = await self._inspect(name, account_id)
            if container and container.get('State', {}).get('Running'):
                await self._request('POST', f'/containers/{name}/stop', params={'t': 10})
        self._running[account_id] = False

    async def stop(self, account_id: str) -> None:
        self._validate_account(account_id)
        async with self._locks.setdefault(account_id, asyncio.Lock()):
            await self._stop(account_id)

    def is_running(self, account_id: str) -> bool:
        return self._running.get(account_id, False)

    async def _monitor(self) -> None:
        while True:
            await asyncio.sleep(5)
            for account_id, name in list(self._containers.items()):
                try:
                    data = await self._inspect(name, account_id)
                    self._running[account_id] = bool(data and data.get('State', {}).get('Running'))
                except Exception:
                    self._running[account_id] = False

    async def close(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()
            await asyncio.gather(self._monitor_task, return_exceptions=True)
            self._monitor_task = None
        results = await asyncio.gather(*(self.stop(account_id) for account_id in list(self._containers)), return_exceptions=True)
        if any(isinstance(result, Exception) for result in results):
            logger.warning('部分 NapCat 容器未能停止，请检查 Docker 服务和资源归属')
        if self._client:
            await self._client.aclose()
            self._client = None
            self._version = None
