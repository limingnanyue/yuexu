"""统一消息段结构（开发文档第 5 章）：上层业务只使用本结构，适配器负责翻译。

示例::

    payload = MessagePayload.from_text("你好")
    payload.add(MessageSegment.emoji("happy01"))
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from backend.common.constants import (
    MessageScene,
    Platform,
    SegmentType,
    group_session_key,
    private_session_key,
)


class MessageSegment(BaseModel):
    """单个消息段。"""

    type: str
    content: str | None = None       # text
    emoji_key: str | None = None     # emoji
    file_path: str | None = None     # voice / image
    url: str | None = None           # image / voice 远程地址
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def text(cls, content: str) -> "MessageSegment":
        return cls(type=SegmentType.TEXT.value, content=content)

    @classmethod
    def emoji(cls, emoji_key: str) -> "MessageSegment":
        return cls(type=SegmentType.EMOJI.value, emoji_key=emoji_key)

    @classmethod
    def voice(cls, file_path: str) -> "MessageSegment":
        return cls(type=SegmentType.VOICE.value, file_path=file_path)

    @classmethod
    def image(cls, file_path: str | None = None, url: str | None = None) -> "MessageSegment":
        return cls(type=SegmentType.IMAGE.value, file_path=file_path, url=url)

    @classmethod
    def at(cls, user_id: str) -> "MessageSegment":
        return cls(type=SegmentType.AT.value, data={"user_id": user_id})

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class MessagePayload(BaseModel):
    """一条待发送消息（text / emoji / voice / image 组合）。"""

    segments: list[MessageSegment] = Field(default_factory=list)

    @classmethod
    def from_text(cls, content: str) -> "MessagePayload":
        return cls(segments=[MessageSegment.text(content)] if content else [])

    @classmethod
    def from_segments(cls, segments: list[MessageSegment]) -> "MessagePayload":
        return cls(segments=segments)

    @property
    def text(self) -> str:
        """拼接全部文本段。"""
        return "".join(
            segment.content or ""
            for segment in self.segments
            if segment.type == SegmentType.TEXT.value
        )

    @property
    def is_empty(self) -> bool:
        return not any(
            segment.content or segment.emoji_key or segment.file_path or segment.url
            for segment in self.segments
        )

    def add(self, segment: MessageSegment) -> "MessagePayload":
        self.segments.append(segment)
        return self

    def add_text(self, content: str) -> "MessagePayload":
        if content:
            self.segments.append(MessageSegment.text(content))
        return self

    def add_emoji(self, emoji_key: str) -> "MessagePayload":
        if emoji_key:
            self.segments.append(MessageSegment.emoji(emoji_key))
        return self

    def to_dict(self) -> dict[str, Any]:
        return {"segments": [segment.to_dict() for segment in self.segments]}

    @classmethod
    def from_dict(cls, data: Any) -> "MessagePayload":
        """兼容 {"segments": [...]} / [...] / 纯文本三种存储形态。"""
        if isinstance(data, MessagePayload):
            return data
        if isinstance(data, str):
            return cls.from_text(data)
        if isinstance(data, list):
            return cls(segments=[MessageSegment(**item) for item in data])
        if isinstance(data, dict):
            if "segments" in data:
                return cls(segments=[MessageSegment(**item) for item in data["segments"]])
            if data.get("content"):
                return cls.from_text(str(data["content"]))
        return cls()


class SenderInfo(BaseModel):
    """发送者信息。"""

    user_id: str = ""
    nickname: str = ""
    card: str = ""
    role: str = "member"   # member / admin / owner


class BotEvent(BaseModel):
    """归一化后的机器人事件（消息 / 通知 / 请求）。"""

    bot_id: str
    platform: Platform = Platform.QQ
    post_type: str = "message"          # message / notice / request / meta_event
    sub_type: str | None = None         # group_increase / group_decrease ...
    scene: MessageScene = MessageScene.PRIVATE
    user_id: str = ""
    group_id: str | None = None
    message_id: str | None = None
    self_id: str = ""
    segments: list[MessageSegment] = Field(default_factory=list)
    raw_message: str = ""
    sender: SenderInfo = Field(default_factory=SenderInfo)
    is_at_me: bool = False
    operator_id: str | None = None
    target_id: str | None = None
    timestamp: int = Field(default_factory=lambda: int(time.time()))
    raw: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None

    @property
    def text(self) -> str:
        """消息纯文本（去掉 @ / 图片等非文本段）。"""
        return "".join(
            segment.content or ""
            for segment in self.segments
            if segment.type == SegmentType.TEXT.value
        ).strip()

    @property
    def is_group(self) -> bool:
        return self.scene == MessageScene.GROUP and bool(self.group_id)

    def session_key(self) -> str:
        """按开发文档 4.6 生成上下文会话 key。"""
        if self.is_group:
            return group_session_key(self.bot_id, str(self.group_id), self.user_id)
        return private_session_key(self.bot_id, self.user_id)

    def target_id_for_send(self) -> str:
        """回复目标：群聊回群，私聊回人。"""
        return str(self.group_id) if self.is_group else self.user_id


class LoginQrcode(BaseModel):
    """登录二维码信息。"""

    qrcode_id: str | None = None
    image_base64: str | None = None
    image_url: str | None = None
    file_path: str | None = None
    expires_in: int = 120
    raw: dict[str, Any] = Field(default_factory=dict)


class LoginState(BaseModel):
    """扫码登录状态。"""

    status: str                      # waiting_qr / scanning / online / offline / error
    message: str = ""
    account_no: str | None = None
    nickname: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
