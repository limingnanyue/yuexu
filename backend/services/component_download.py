"""校验固定发行包，复用离线缓存并在网络中断后安全续传。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import httpx

from backend.common.exceptions import AppError

MAX_COMPONENT_BYTES = 512 * 1024 * 1024


class _RestartDownload(Exception):
    pass


class _BadPackage(Exception):
    pass


def _verified(path: Path, expected: str) -> bool:
    if not path.is_file() or path.stat().st_size > MAX_COMPONENT_BYTES:
        return False
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest() == expected


async def download_component(client: httpx.AsyncClient, urls: list[str], archive: Path,
                             expected_sha256: str, report=None) -> None:
    """仅接受 HTTPS 源；缓存和所有镜像都必须通过调用方固定的 SHA-256。"""
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
        raise AppError("组件校验配置无效，必须提供固定 SHA-256")
    expected = expected_sha256.lower()
    partial = archive.with_suffix(".part")
    metadata = partial.with_suffix(".part.json")

    def report_progress(message):
        if report:
            report("downloading", message)

    def discard_partial():
        partial.unlink(missing_ok=True)
        metadata.unlink(missing_ok=True)

    try:
        if _verified(archive, expected):
            report_progress("已校验并复用本地组件缓存")
            return
        if not urls:
            raise AppError("没有可用的组件下载源，请配置 HTTPS 下载地址后重试")
        for url in urls:
            try:
                parsed = urlsplit(url)
                if parsed.port == 0:
                    raise ValueError("Invalid port")
            except (ValueError, TypeError) as exc:
                raise AppError("组件下载源配置无效，请填写完整的 HTTPS 地址") from exc
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise AppError("组件下载源配置无效，仅支持不含账号密码的 HTTPS 地址")
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.unlink(missing_ok=True)
        last_error = "网络连接失败"
        for source_index, url in enumerate(dict.fromkeys(urls)):
            if source_index:
                report_progress("当前下载源不可用，正在切换备用源")
            source = hashlib.sha256(url.encode()).hexdigest()
            for attempt in range(3):
                if attempt:
                    report_progress(f"下载中断，正在第 {attempt + 1}/3 次尝试（可续传部分将保留）")
                    await asyncio.sleep(min(attempt, 2))
                try:
                    state = json.loads(metadata.read_text("utf-8")) if metadata.exists() else {}
                except (ValueError, OSError):
                    state = {}
                offset = partial.stat().st_size if partial.is_file() else 0
                etag = state.get("etag") if isinstance(state, dict) else None
                total = state.get("total") if isinstance(state, dict) else None
                resumable = (isinstance(state, dict) and state.get("source") == source and
                             isinstance(etag, str) and re.fullmatch(r'"[\x21\x23-\x7e]*"', etag) and
                             0 < offset <= MAX_COMPONENT_BYTES and
                             (total is None or type(total) is int and offset <= total <= MAX_COMPONENT_BYTES))
                headers = {"Accept-Encoding": "identity"}
                if resumable:
                    headers.update({"Range": f"bytes={offset}-", "If-Range": etag})
                else:
                    offset = 0
                try:
                    started = monotonic()
                    async with client.stream("GET", url, headers=headers) as response:
                        if response.status_code == 416:
                            match = re.fullmatch(r"bytes \*/([0-9]+)", response.headers.get("content-range", ""))
                            if (resumable and match and int(match[1]) == offset and
                                    _verified(partial, expected)):
                                partial.replace(archive)
                                metadata.unlink(missing_ok=True)
                                return
                            raise _RestartDownload("服务器不接受续传位置，已重新开始")
                        response.raise_for_status()
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            raise _BadPackage("下载源返回了不支持的压缩格式")
                        length = response.headers.get("content-length")
                        if length is not None and not re.fullmatch(r"[0-9]+", length):
                            raise _RestartDownload("下载源返回的组件大小无效")
                        length = int(length) if length is not None else None
                        if response.status_code == 206:
                            match = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+)", response.headers.get("content-range", ""))
                            if not resumable or not match:
                                raise _RestartDownload("下载源的续传响应无效")
                            start, end, complete = map(int, match.groups())
                            if (start != offset or end != complete - 1 or end < start or
                                    total is not None and total != complete or
                                    length is not None and length != end - start + 1 or
                                    response.headers.get("etag", etag) != etag):
                                raise _RestartDownload("下载源的续传位置或版本不一致，已重新开始")
                            total = complete
                        elif response.status_code == 200:
                            offset, total = 0, length
                        else:
                            raise _RestartDownload("下载源未返回组件内容")
                        if total is not None and total > MAX_COMPONENT_BYTES:
                            raise _BadPackage("组件安装包大小异常，已中止下载")
                        etag = response.headers.get("etag", etag if offset else None)
                        with partial.open("ab" if offset else "wb") as handle:
                            metadata.write_text(json.dumps({"source": source, "etag": etag, "total": total}), "utf-8")
                            downloaded = offset
                            shown = -1
                            async for chunk in response.aiter_bytes():
                                downloaded += len(chunk)
                                if downloaded > MAX_COMPONENT_BYTES or total is not None and downloaded > total:
                                    raise _BadPackage("组件安装包大小异常，已中止下载")
                                handle.write(chunk)
                                if monotonic() - started >= 600:
                                    raise httpx.ReadTimeout("Component attempt exceeded 600 seconds")
                                progress = downloaded * 100 // total if total else downloaded // 1048576
                                if progress != shown:
                                    shown = progress
                                    suffix = f"{progress}%" if total else f"{progress} MB"
                                    report_progress(f"正在下载登录组件 {suffix}" + ("（断点续传）" if offset else ""))
                            if total is not None and downloaded != total:
                                raise httpx.ReadError("Incomplete component download")
                    if not _verified(partial, expected):
                        raise _BadPackage("组件安装包校验失败，已丢弃损坏文件")
                    partial.replace(archive)
                    metadata.unlink(missing_ok=True)
                    return
                except _BadPackage as exc:
                    last_error = str(exc)
                    discard_partial()
                    break
                except _RestartDownload as exc:
                    last_error = str(exc)
                    discard_partial()
                except httpx.HTTPError as exc:
                    last_error = f"下载源返回 HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else "网络超时或连接中断"
        raise AppError(f"组件下载失败：{last_error}。请检查网络或配置备用下载源后重试；已保留可续传的下载进度",
                       code="COMPONENT_DOWNLOAD_FAILED", status_code=502)
    except OSError as exc:
        raise AppError("组件缓存读写失败，请检查磁盘空间和目录权限后重试", code="COMPONENT_CACHE_FAILED", status_code=500) from exc
