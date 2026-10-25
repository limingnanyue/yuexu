"""表情包库接口。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel

from backend.common.exceptions import ValidationError
from backend.dependencies import (
    get_account_service,
    get_emoji_service,
    require_admin,
)
from backend.routers.serializers import emoji_out
from backend.services.account_service import AccountService
from backend.services.emoji_service import EmojiService

router = APIRouter(prefix="/api/emojis", tags=["表情包库"])


class EmojiPayload(BaseModel):
    key: str | None = None
    alias: str | None = None
    category: str | None = None
    file_path: str | None = None
    weight: int | None = None
    enabled: bool | None = None


class EmojiTestRequest(BaseModel):
    bot_id: str
    target_type: str = "group"
    target_id: str


@router.get("", summary="表情列表")
async def list_emojis(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    category: str | None = None,
    keyword: str | None = None,
    _=Depends(require_admin),
    service: EmojiService = Depends(get_emoji_service),
):
    items, total = await service.list_page(
        page, page_size, category=category, keyword=keyword
    )
    return {
        "items": [emoji_out(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.post("/upload", summary="上传表情图片")
async def upload_emoji(
    file: UploadFile = File(...),
    key: str = Form(""),
    alias: str = Form(""),
    category: str = Form("default"),
    weight: int = Form(1),
    _=Depends(require_admin),
    service: EmojiService = Depends(get_emoji_service),
):
    content = await file.read()
    item = await service.upload(
        key=key,
        alias=alias,
        category=category,
        weight=weight,
        filename=file.filename or "emoji.png",
        content=content,
    )
    return emoji_out(item)


@router.post("", summary="登记已有表情文件")
async def create_emoji(
    payload: EmojiPayload,
    _=Depends(require_admin),
    service: EmojiService = Depends(get_emoji_service),
):
    return emoji_out(await service.create(payload.model_dump(exclude_none=True)))


@router.put("/{emoji_id}", summary="更新表情")
async def update_emoji(
    emoji_id: str,
    payload: EmojiPayload,
    _=Depends(require_admin),
    service: EmojiService = Depends(get_emoji_service),
):
    return emoji_out(await service.update(emoji_id, payload.model_dump(exclude_none=True)))


@router.delete("/{emoji_id}", summary="删除表情")
async def delete_emoji(
    emoji_id: str,
    _=Depends(require_admin),
    service: EmojiService = Depends(get_emoji_service),
):
    await service.delete(emoji_id)
    return {"message": "已删除"}


@router.post("/{emoji_id}/test-send", summary="测试发送表情")
async def test_send(
    emoji_id: str,
    payload: EmojiTestRequest,
    _=Depends(require_admin),
    service: EmojiService = Depends(get_emoji_service),
    accounts: AccountService = Depends(get_account_service),
):
    raise ValidationError("控制台不主动发送测试消息，请在私聊中向机器人发消息测试")
