"""通用工具：ID、时间、文件、文本、随机延时、深合并等（无业务逻辑）。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import secrets
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, TypeVar

T = TypeVar("T")

_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\s]+')


# ---------------------------------------------------------------------------
# 时间
# ---------------------------------------------------------------------------

def now() -> datetime:
    """当前本地时间（数据库统一存本地 naive 时间，便于后台直接展示）。"""
    return datetime.now()


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def ts_to_datetime(timestamp: int | float) -> datetime:
    return datetime.fromtimestamp(timestamp)


def dt_to_iso(value: datetime | None) -> str | None:
    return value.isoformat(timespec="seconds") if value else None


def iso_to_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_expired(updated_at: datetime | str | None, ttl_seconds: int) -> bool:
    """判断会话是否超过 TTL。"""
    if not updated_at:
        return True
    moment = iso_to_dt(updated_at) if isinstance(updated_at, str) else updated_at
    if moment is None:
        return True
    return now() - moment > timedelta(seconds=ttl_seconds)


# ---------------------------------------------------------------------------
# ID / 安全
# ---------------------------------------------------------------------------

def new_id(prefix: str = "") -> str:
    """短随机 ID，例如 acc_3f9a1c2b7d4e5f60。"""
    token = secrets.token_hex(8)
    return f"{prefix}{token}" if prefix else token


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def mask_secret(value: str | None, keep: int = 4) -> str:
    """密钥脱敏展示。"""
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * (len(value) - keep * 2)}{value[-keep:]}"


# ---------------------------------------------------------------------------
# 文本
# ---------------------------------------------------------------------------

def truncate(text: str | None, limit: int, suffix: str = "…") -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)] + suffix


def split_text(text: str, size: int) -> list[str]:
    """按长度拆分文本（用于 TTS 长文本截断）。"""
    if size <= 0:
        return [text]
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]


def clean_text(text: str, max_length: int = 4000) -> str:
    """基础清洗：去除不可见控制字符、压缩空白、截断。"""
    if not text:
        return ""
    cleaned = "".join(
        ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C"
    )
    cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines()).strip()
    return cleaned[:max_length]


def extract_keywords(text: str, limit: int = 6) -> list[str]:
    """轻量关键词提取（中文按 2-4 字切片去停用词，英文按单词）。

    仅作为未安装 Chroma 时的关键词检索降级方案，不追求分词精度。
    """
    if not text:
        return []
    stopwords = {
        "的", "了", "是", "我", "你", "他", "她", "它", "在", "有", "和", "就",
        "不", "也", "都", "这", "那", "吗", "呢", "啊", "呀", "吧", "一个",
        "什么", "怎么", "可以", "这个", "那个", "我们", "你们", "他们",
    }
    words: list[str] = []
    latin = re.findall(r"[A-Za-z][A-Za-z0-9_+-]{1,}", text)
    words.extend(w.lower() for w in latin)
    for chunk in re.findall(r"[\u4e00-\u9fa5]{2,8}", text):
        for size in (4, 3, 2):
            for i in range(0, max(len(chunk) - size + 1, 0)):
                word = chunk[i : i + size]
                if word not in stopwords:
                    words.append(word)
    seen: set[str] = set()
    result: list[str] = []
    for word in words:
        if word in seen:
            continue
        seen.add(word)
        result.append(word)
        if len(result) >= limit:
            break
    return result


# ---------------------------------------------------------------------------
# 文件
# ---------------------------------------------------------------------------

def ensure_dir(path: str | Path) -> Path:
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def safe_filename(name: str, fallback: str = "file") -> str:
    """生成安全的文件名（保留扩展名）。"""
    name = unicodedata.normalize("NFKC", name or "").strip()
    if not name:
        return fallback
    stem, dot, suffix = name.rpartition(".")
    if dot and len(suffix) <= 8:
        stem = _UNSAFE_FILENAME.sub("_", stem)[:60] or fallback
        return f"{stem}.{suffix}"
    return _UNSAFE_FILENAME.sub("_", name)[:60] or fallback


def file_size_str(size: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}"
        value /= 1024
    return f"{size}B"


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=_json_default)


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    return str(value)


# ---------------------------------------------------------------------------
# 异步
# ---------------------------------------------------------------------------

def random_delay_seconds(min_seconds: float, max_seconds: float) -> float:
    low = max(0.0, float(min_seconds))
    high = max(low, float(max_seconds))
    return round(random.uniform(low, high), 2)


async def human_delay(min_seconds: float, max_seconds: float) -> float:
    """拟人化随机延时，规避平台高频风控。"""
    delay = random_delay_seconds(min_seconds, max_seconds)
    if delay > 0:
        await asyncio.sleep(delay)
    return delay


async def retry_async(
    factory: Callable[[], Awaitable[T]],
    attempts: int = 3,
    delay: float = 0.5,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """有限次数重试（指数退避）。"""
    last_error: BaseException | None = None
    for index in range(max(1, attempts)):
        try:
            return await factory()
        except exceptions as exc:  # noqa: PERF203 - 需要逐次退避
            last_error = exc
            if index < attempts - 1:
                await asyncio.sleep(delay * (index + 1))
    raise last_error  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------

def deep_merge(base: dict, patch: dict) -> dict:
    """递归合并配置（patch 覆盖 base），返回新字典。"""
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def chunked(items: Iterable[T], size: int) -> Iterable[list[T]]:
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
