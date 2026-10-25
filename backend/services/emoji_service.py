"""表情包库（开发文档 4.10）：标签解析、关键词绑定、随机权重、文件管理。"""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exceptions import ConflictError, NotFoundError, ValidationError
from backend.common.logger import get_logger
from backend.common.message import MessageSegment
from backend.common.utils import ensure_dir, safe_filename
from backend.core.config_loader import get_config
from backend.database.models import Character, EmojiItem
from backend.repositories.emoji_repo import EmojiRepo

logger = get_logger("yuexu.service.emoji")

_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class EmojiService:
    """表情资源管理与回复组装。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = EmojiRepo(session)
        self.config = get_config()
        self.lib_dir = ensure_dir(
            self.config.resolve_path(str(self.config.get("emoji.lib_dir", "static/emoji_lib")))
        )

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def list_page(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        category: str | None = None,
        keyword: str | None = None,
    ) -> tuple[list[EmojiItem], int]:
        items = await self.repo.list(limit=1000, order_by="created_at", desc=True)
        if category:
            items = [item for item in items if item.category == category]
        if keyword:
            lowered = keyword.lower()
            items = [
                item for item in items
                if lowered in item.key.lower() or lowered in (item.alias or "").lower()
            ]
        total = len(items)
        start = max(page - 1, 0) * page_size
        return items[start : start + page_size], total

    async def list_enabled(self) -> list[EmojiItem]:
        return await self.repo.list_enabled()

    async def get(self, emoji_id: str) -> EmojiItem:
        item = await self.repo.get(emoji_id)
        if not item:
            raise NotFoundError("表情不存在")
        return item

    async def resolve(self, key: str) -> EmojiItem | None:
        return await self.repo.find_by_key_or_alias(key)

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    async def create(self, data: dict[str, Any]) -> EmojiItem:
        key = str(data.get("key") or "").strip()
        if not key:
            raise ValidationError("表情 key 不能为空")
        if await self.repo.get_by_key(key):
            raise ConflictError("表情 key 已存在")
        file_path = str(data.get("file_path") or "")
        if not file_path:
            raise ValidationError("表情文件路径不能为空")
        return await self.repo.create(
            key=key,
            alias=str(data.get("alias") or key),
            category=str(data.get("category") or "default"),
            file_path=file_path,
            weight=max(1, int(data.get("weight") or self.config.get("emoji.default_weight", 1))),
            enabled=bool(data.get("enabled", True)),
        )

    async def update(self, emoji_id: str, data: dict[str, Any]) -> EmojiItem:
        item = await self.get(emoji_id)
        values: dict[str, Any] = {}
        if "alias" in data:
            values["alias"] = str(data["alias"] or "")
        if "category" in data:
            values["category"] = str(data["category"] or "default")
        if "weight" in data:
            values["weight"] = max(1, int(data["weight"] or 1))
        if "enabled" in data:
            values["enabled"] = bool(data["enabled"])
        if "file_path" in data and data["file_path"]:
            values["file_path"] = str(data["file_path"])
        if "key" in data and data["key"] and data["key"] != item.key:
            if await self.repo.get_by_key(str(data["key"])):
                raise ConflictError("表情 key 已存在")
            values["key"] = str(data["key"])
        return await self.repo.update(item, **values)

    async def delete(self, emoji_id: str) -> None:
        item = await self.get(emoji_id)
        await self.repo.delete(item)

    async def upload(
        self,
        *,
        key: str,
        alias: str,
        category: str,
        weight: int,
        filename: str,
        content: bytes,
    ) -> EmojiItem:
        suffix = Path(filename).suffix.lower()
        if suffix not in _ALLOWED_SUFFIXES:
            raise ValidationError(f"不支持的图片格式：{suffix or '未知'}")
        if not content:
            raise ValidationError("上传文件为空")
        key = key.strip() or Path(filename).stem
        if await self.repo.get_by_key(key):
            raise ConflictError("表情 key 已存在")
        target = safe_filename(f"{key}{suffix}")
        target_path = self.lib_dir / target
        target_path.write_bytes(content)
        return await self.repo.create(
            key=key,
            alias=alias or key,
            category=category or "default",
            file_path=str(target_path),
            weight=max(1, weight),
            enabled=True,
        )

    # ------------------------------------------------------------------
    # 回复组装
    # ------------------------------------------------------------------
    async def pick_random(self, category: str | None = None) -> EmojiItem | None:
        items = await self.repo.list_enabled(category)
        if not items:
            return None
        weights = [max(1, item.weight) for item in items]
        return random.choices(items, weights=weights, k=1)[0]

    async def parse_reply(
        self,
        text: str,
        *,
        character: Character | None = None,
        enabled: bool = True,
        max_emojis: int = 2,
    ) -> tuple[str, list[MessageSegment]]:
        """解析 LLM 回复里的 ``[开心]`` 标签，返回 (清洗文本, 表情段)。"""
        segments: list[MessageSegment] = []
        pattern = str(self.config.get("emoji.tag_pattern", r"\[([^\[\]]{1,8})\]"))
        if not enabled:
            return re.sub(pattern, "", text).strip(), segments

        cleaned = text

        # 逐个标签解析（异步查询，不能放在 re.sub 回调中）
        for match in list(re.finditer(pattern, text)):
            if len(segments) >= max_emojis:
                cleaned = cleaned.replace(match.group(0), "")
                continue
            item = await self.resolve(match.group(1))
            if item and item.enabled:
                segments.append(MessageSegment.emoji(item.key))
                cleaned = cleaned.replace(match.group(0), "")
            else:
                # 未登记的标签不保留原文，避免把 [开心] 直接发出去
                cleaned = cleaned.replace(match.group(0), "")

        if character is not None and character.emoji_keys and len(segments) < max_emojis:
            for key in character.emoji_keys:
                item = await self.resolve(str(key))
                if item and item.enabled:
                    segments.append(MessageSegment.emoji(item.key))
                    break

        return cleaned.strip(), segments

    async def resolve_segments(self, segments: list[MessageSegment]) -> list[MessageSegment]:
        """补全表情段的真实文件路径（适配器只需负责发送）。"""
        resolved: list[MessageSegment] = []
        for segment in segments:
            if segment.type == "emoji" and segment.emoji_key and not segment.file_path:
                item = await self.resolve(segment.emoji_key)
                if item and item.enabled and self._file_exists(item.file_path):
                    segment.file_path = item.file_path
                    resolved.append(segment)
                else:
                    logger.warning("表情资源缺失，已跳过：%s", segment.emoji_key)
                continue
            resolved.append(segment)
        return resolved

    def _file_exists(self, file_path: str) -> bool:
        if not file_path:
            return False
        path = Path(file_path)
        if not path.is_absolute():
            path = self.config.root / path
        return path.exists()
