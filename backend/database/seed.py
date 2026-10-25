"""初始化数据：后台超管、默认人设、默认模型占位。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.character_defaults import DEFAULT_CHARACTER as _DEFAULT_CHARACTER
from backend.common.logger import get_logger
from backend.repositories.character_repo import CharacterRepo
from backend.repositories.model_repo import ModelRepo
from backend.services.auth_service import AuthService

logger = get_logger("yuexu.seed")


async def seed_initial_data(session: AsyncSession) -> dict[str, Any]:
    """幂等初始化缺失数据：超管、默认人设、默认模型、兜底话题。"""
    created: dict[str, Any] = {}

    admin = await AuthService(session).ensure_default_admin()
    if admin:
        created["admin"] = admin.username
        logger.warning(
            "已创建初始超管账号：%s（请登录后台立即修改密码）", admin.username
        )

    character_repo = CharacterRepo(session)
    if await character_repo.count() == 0:
        character = await character_repo.create(**_DEFAULT_CHARACTER)
        created["character"] = character.name
        logger.info("已创建默认人设：%s", character.name)

    model_repo = ModelRepo(session)
    if await model_repo.count() == 0:
        model = await model_repo.create(
            name="DeepSeek Chat（待填写 Key）",
            provider="openai",
            base_url="https://api.deepseek.com",
            api_key="",
            model_name="deepseek-chat",
            temperature=0.8,
            max_tokens=1024,
            timeout=60,
            is_default=True,
            enabled=True,
        )
        created["model"] = model.name
        logger.warning("已创建默认模型配置，请在后台填写 API Key 后使用")

    # 活力 Agent 兜底话题素材（仅首次建库时写入，后续由后台维护）
    from backend.repositories.vitality_repo import TopicBankRepo

    topic_repo = TopicBankRepo(session)
    if await topic_repo.count() == 0:
        for content, tag, weight in _DEFAULT_TOPICS:
            await topic_repo.create(topic_content=content, tag=tag, weight=weight)
        created["vitality_topics"] = len(_DEFAULT_TOPICS)
        logger.info("已写入活力 Agent 默认话题素材 %s 条", len(_DEFAULT_TOPICS))

    return created


# 兜底话题模板：只在记忆与最近聊天都没有素材时才会被用到
_DEFAULT_TOPICS = [
    ("最近有没有发现什么有意思的小事呀？", "question", 8),
    ("刚刚看到一个好玩的东西，突然想跟你分享下", "fun", 6),
    ("突然想起来之前聊过的那件事，后来怎么样啦？", "memory", 6),
    ("今天过得还好吗？随便聊聊也行", "normal", 5),
    ("刚忙完自己的事，你现在方便说会儿话吗", "normal", 4),
    ("你上次提到的那件事我一直记着呢，有新进展吗", "memory", 5),
    ("这会儿在干嘛呀？我在做自己喜欢的事，突然想到你", "fun", 4),
    ("有个问题想听听你的看法，你最近对什么上头了吗", "question", 5),
]
