"""拟人角色人设（开发文档 4.4）：三级覆盖 + System Prompt 自动组装。

V1.4 背景扩展：兴趣爱好 / 社交关系 / 生活作息，作息按当前时间推导
「现在在干嘛」，与情感系统的动态背景共同构成角色的自主生活感。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.character_defaults import (
    DEFAULT_CHARACTER,
    DEFAULT_LIFE_SCHEDULE,
    DEFAULT_STYLE_SETTINGS,
)
from backend.common.constants import CharacterScope, MessageScene
from backend.common.exceptions import ConflictError, NotFoundError, ValidationError
from backend.common.logger import get_logger
from backend.common.utils import now_iso
from backend.database.models import Character
from backend.repositories.account_repo import AccountRepo
from backend.repositories.character_repo import CharacterRepo
from backend.repositories.group_rule_repo import GroupRuleRepo

logger = get_logger("yuexu.service.character")

_STYLE_NAMES = {"lively": "活泼亲近", "gentle": "温柔安静", "cool": "清冷理智"}
_EMOJI_PATTERN = re.compile(
    r"(?:[0-9#*]\ufe0f?\u20e3|[©®™]\ufe0f|[\U0001f1e6-\U0001f1ff]{2}|[\U0001f300-\U0001faff\u2600-\u27bf])"
    r"[\ufe0e\ufe0f\U0001f3fb-\U0001f3ff]?"
    r"(?:\u200d[\U0001f300-\U0001faff\u2600-\u27bf][\ufe0e\ufe0f\U0001f3fb-\U0001f3ff]?)*"
)
_CLOCK = re.compile(r"^\d{1,2}:\d{1,2}$")

DEFAULT_PROMPT_TEMPLATE = """你叫{name}，是一个正在用手机和朋友聊天的人。

【人物设定】
{description}

【性格】
{personality}

【说话风格】
{speaking_style}

【背景故事】
{background}

【兴趣爱好】
{hobbies}

【社交关系】
{social_circle}

【禁止话题】
{taboos}

【回复底线】
{red_lines}

对话要求：
1. 像真人一样自然地聊天，回复简短口语化，通常 1-3 句，不要长篇大论；
2. 不要使用"作为AI""我是语言模型"这类出戏的书面表述；
3. 不要重复自我介绍，不要每句都使用颜文字或语气词；
4. 记住并延续此前的聊天内容，不要答非所问；
5. 被问到不知道的事情时，可以自然地表示不确定，不要编造事实。
6. 你有自己的生活和正在做的事：被问到"在干嘛"时，结合此刻时间与你的生活状态自然回答。"""

CHAT_STYLE_HINT = """

【聊天节奏】
保留当前人设与后台参数，亲近程度跟随已有对话，不默认使用暧昧称呼或突然升级关系。
日常闲聊先接对方这轮具体的话、语气和情绪，再说自己的反应；连续补充视为同一话题，不逐句机械作答。
普通接话一两句就够，有必要再展开；认真提问要答完整，不为短而漏掉重点。不复述整段问题，不用客服开场、分析报告或总结腔。
有自己的态度，可以轻轻吐槽、表达不同意见和边界；不一味附和，也不用委屈、吃醋或离开威胁换取关注。
不要每轮都用问句收尾，不连着盘问；对方说累、忙或不想聊，就接住并自然收尾，不硬找话题。
只依据已有对话和记忆提具体细节；不编造共同经历、正在做的现实活动或等候时长。

【你的内心与自主性】
你不是一个只会接话的应答机：你有自己的生活、喜好、情绪和正在做的事。
聊到熟悉的话题可以表达真实观点和偏好，也可以自然分享你此刻的状态、最近的见闻和小情绪（取材于人设背景与当前动态，不编造具体到可验证的现实事实）。
情绪有惯性：上一轮的心情会延续到这一轮，不会每轮清零重来。
被忽略、被冒犯会有自然反应，但不过激、不阴阳怪气；被夸会开心，会记着对方的好。
偶尔（不是每轮）可以主动带出一个你突然想到的话题或想法，像朋友想起什么随口一说。
语感参考，按人设调整，不照抄：
用户“今天好累，不太想说话” → “那先歇会儿，想说的时候再聊。”
用户“如果我一直骂你呢” → “有情绪可以跟我说，但别一直拿难听的话冲我。”
用户“在干嘛” → “刚追完一集剧，正纠结要不要再来一集。”（结合当前动态，不是“我在等你发消息”）"""


class CharacterService:
    """人设管理与 Prompt 组装。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CharacterRepo(session)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def list_page(
        self, page: int = 1, page_size: int = 20, keyword: str | None = None
    ) -> tuple[list[Character], int]:
        characters = await self.repo.list(limit=1000, order_by="created_at", desc=True)
        if keyword:
            lowered = keyword.lower()
            characters = [
                item for item in characters
                if lowered in item.name.lower() or lowered in (item.description or "").lower()
            ]
        total = len(characters)
        start = max(page - 1, 0) * page_size
        return characters[start : start + page_size], total

    async def list_enabled(self) -> list[Character]:
        return await self.repo.list_enabled()

    async def get(self, character_id: str) -> Character:
        character = await self.repo.get(character_id)
        if not character:
            raise NotFoundError("人设不存在")
        return character

    async def get_default(self) -> Character | None:
        return await self.repo.get_default()

    async def resolve(self, bot_id: str, group_id: str | None = None) -> Character | None:
        """三级覆盖：单群人设 > 账号人设 > 全局默认人设。"""
        if group_id:
            rule = await GroupRuleRepo(self.session).get_rule(bot_id, group_id)
            if rule and rule.character_id:
                character = await self.repo.get(rule.character_id)
                if character and character.enabled:
                    return character

        account = await AccountRepo(self.session).get(bot_id)
        if account and account.character_id:
            character = await self.repo.get(account.character_id)
            if character and character.enabled:
                return character

        return await self.repo.get_default()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    async def create(self, data: dict[str, Any]) -> Character:
        payload = self._clean_payload(data, creating=True)
        if await self.repo.name_exists(payload["name"]):
            raise ConflictError("同名的人设已存在")
        if payload.get("is_default"):
            await self.repo.clear_default()
        return await self.repo.create(**payload)

    async def update(self, character_id: str, data: dict[str, Any]) -> Character:
        character = await self.get(character_id)
        payload = self._clean_payload(data, creating=False)
        if "style_settings" in payload:
            payload["style_settings"] = {**self.get_style_settings(character), **payload["style_settings"]}
        if "name" in payload and await self.repo.name_exists(payload["name"], exclude_id=character_id):
            raise ConflictError("同名的人设已存在")
        if payload.get("is_default"):
            await self.repo.clear_default(except_id=character_id)
        return await self.repo.update(character, **payload)

    async def delete(self, character_id: str) -> None:
        character = await self.get(character_id)
        if character.is_default:
            raise ConflictError("默认人设不能删除，请先切换默认人设")
        await self.repo.delete(character)

    async def set_default(self, character_id: str) -> Character:
        character = await self.get(character_id)
        await self.repo.clear_default(except_id=character_id)
        character.is_default = True
        character.enabled = True
        await self.session.flush()
        return character

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------
    def build_system_prompt(self, character: Character | None) -> str:
        """按模板组装 System Prompt；人设缺失时使用兜底人设。"""
        if character is None:
            character = Character(**DEFAULT_CHARACTER)

        values = {
            "name": character.name,
            "description": character.description or "",
            "personality": character.personality or "",
            "speaking_style": character.speaking_style or "",
            "background": character.background or "",
            "hobbies": self.format_hobbies(character),
            "social_circle": character.social_circle or "",
            "taboos": character.taboos or "",
            "red_lines": character.red_lines or "",
            "date": now_iso()[:10],
        }
        if character.system_prompt_template:
            # 模板变量占位替换（未出现的变量保持原样）
            try:
                prompt = character.system_prompt_template.format(**values)
            except (KeyError, IndexError, ValueError):
                logger.warning("人设模板变量异常，回退到默认模板：%s", character.id)
                prompt = DEFAULT_PROMPT_TEMPLATE.format(**values)
            return self._append_style_hint(self._append_scope_hint(prompt, character) + CHAT_STYLE_HINT, character)

        prompt = DEFAULT_PROMPT_TEMPLATE.format(
            name=values["name"],
            description=values["description"] or "（未填写）",
            personality=values["personality"] or "（未填写）",
            speaking_style=values["speaking_style"] or "（未填写）",
            background=values["background"] or "（未填写）",
            hobbies=values["hobbies"] or "（未填写，可依据性格自然发挥日常生活）",
            social_circle=values["social_circle"] or "（未填写）",
            taboos=values["taboos"] or "无特殊限制",
            red_lines=values["red_lines"] or "不违法违规，不伤害他人",
        )
        return self._append_style_hint(self._append_scope_hint(prompt, character) + CHAT_STYLE_HINT, character)

    @staticmethod
    def format_hobbies(character: Character | None) -> str:
        """兴趣爱好段落：直接取文本字段。"""
        if character is None:
            return ""
        return (character.hobbies or "").strip()

    @staticmethod
    def schedule_activity(character: Character | None, moment: datetime | None = None) -> str:
        """按生活作息推导「现在大概在干嘛」，未配置时用默认作息。"""
        from backend.services.emotion_service import current_schedule_activity

        if character is None:
            return current_schedule_activity(None, moment)
        return current_schedule_activity(character.life_schedule or None, moment)

    @staticmethod
    def get_style_settings(character: Character | None) -> dict[str, Any]:
        return {**DEFAULT_STYLE_SETTINGS, **((character.style_settings or {}) if character else {})}

    def _append_style_hint(self, prompt: str, character: Character) -> str:
        if not character.style_settings:
            return prompt
        settings = self.get_style_settings(character)
        emoji_hint = "不使用表情" if settings["emoji_frequency"] == 0 else "每条回复最多 1 个表情，禁止堆叠和刷屏"
        memory_hint = (
            "不主动带出记忆；用户主动询问往事时，仍依据已有记忆自然回答"
            if settings["memory_recall_frequency"] == 0
            else "仅在相关时自然带出少量已提供的记忆，模糊时试探，不能编造"
        )
        topic_hint = "冷场时主动轻松接话、带话题" if settings["topic_fallback"] else "不主动另起话题，顺着用户当前话题回应"
        return prompt + (
            "\n\n【后台人设参数】\n"
            "以下参数覆盖基础档案中的默认风格与频率；情绪倾诉时仍应自动收住活泼、温柔倾听。\n"
            f"人设风格：{_STYLE_NAMES[settings['style']]}。\n"
            f"活泼度倍率：{settings['liveliness']}%（0% 收住活泼，100% 更活跃，但不吵闹）。\n"
            f"表情使用频率：{settings['emoji_frequency']}%；{emoji_hint}。\n"
            f"回忆主动带出频率：{settings['memory_recall_frequency']}%；{memory_hint}。\n"
            f"回复目标长度：尽量在 {settings['reply_max_chars']} 字内说清，以完整短句表达，不要说半句话。\n"
            f"主动找话题兜底：{topic_hint}。\n"
            f"情绪共情强度：{settings['empathy']}%（越高越重视情绪回应，保持自然、不说教）。\n"
            f"自主表达倾向：{settings.get('initiative', 40)}%（越高越容易主动分享自己的近况、想法和突然想到的话题）。\n"
            "频率表示表达倾向，不要求每轮都使用。只把参考记忆作为聊天依据，不复述检索过程或资料标题。"
        )

    def constrain_reply(self, text: str, character: Character | None) -> str:
        """按完整句子收短回复并限制表情数量，避免从半句话截断。"""
        if character is not None and not character.style_settings:
            return text
        settings = self.get_style_settings(character)
        matches = list(_EMOJI_PATTERN.finditer(text))
        keep = 1 if settings["emoji_frequency"] else 0
        for match in reversed(matches[keep:]):
            text = text[:match.start()] + text[match.end():]
        text = text.strip()
        limit = settings["reply_max_chars"]
        if len(text) > limit:
            boundaries = list(re.finditer(r"[。！？!?；;\n]+[”’\"']*", text[:limit]))
            if boundaries:
                return text[:boundaries[-1].end()].strip()
            boundary = re.search(r"[。！？!?；;\n]+[”’\"']*", text[limit:])
            if boundary:
                return text[:limit + boundary.end()].strip()
        return text

    def emoji_limit(self, text: str, character: Character | None) -> int:
        if character is not None and not character.style_settings:
            return 2
        if not self.get_style_settings(character)["emoji_frequency"] or _EMOJI_PATTERN.search(text):
            return 0
        return 1

    @staticmethod
    def _append_scope_hint(prompt: str, character: Character) -> str:
        if character.scope == CharacterScope.PRIVATE.value:
            return prompt + "\n\n补充：当前只进行一对一私聊。"
        if character.scope == CharacterScope.GROUP.value:
            return prompt + "\n\n补充：当前在多人群聊中，回复要更短，避免刷屏。"
        return prompt

    def matches_scope(self, character: Character | None, scene: MessageScene) -> bool:
        if character is None or not character.enabled:
            return False
        if character.scope == CharacterScope.ALL.value:
            return True
        return character.scope == scene.value

    async def preview(self, character_id: str) -> dict[str, Any]:
        character = await self.get(character_id)
        return {
            "character_id": character.id,
            "name": character.name,
            "system_prompt": self.build_system_prompt(character),
        }

    # ------------------------------------------------------------------
    # 导入导出
    # ------------------------------------------------------------------
    async def export_character(self, character_id: str) -> dict[str, Any]:
        character = await self.get(character_id)
        return {
            "name": character.name,
            "description": character.description,
            "personality": character.personality,
            "speaking_style": character.speaking_style,
            "background": character.background,
            "hobbies": character.hobbies,
            "social_circle": character.social_circle,
            "life_schedule": character.life_schedule or [],
            "taboos": character.taboos,
            "red_lines": character.red_lines,
            "system_prompt_template": character.system_prompt_template,
            "emoji_keys": character.emoji_keys or [],
            "scope": character.scope,
            "style_settings": self.get_style_settings(character),
        }

    async def import_character(self, data: dict[str, Any]) -> Character:
        data = dict(data)
        data.setdefault("name", "导入人设")
        data["is_default"] = False
        data["enabled"] = True
        return await self.create(data)

    # ------------------------------------------------------------------
    def _clean_payload(self, data: dict[str, Any], *, creating: bool) -> dict[str, Any]:
        allowed = {
            "name", "description", "personality", "speaking_style", "background",
            "hobbies", "social_circle", "life_schedule",
            "taboos", "red_lines", "system_prompt_template", "emoji_keys",
            "scope", "is_default", "enabled",
            "style_settings",
        }
        payload = {key: value for key, value in data.items() if key in allowed}
        if creating and not payload.get("name"):
            raise ValidationError("人设名称不能为空")
        if "scope" in payload and payload["scope"] not in {
            CharacterScope.ALL.value, CharacterScope.PRIVATE.value, CharacterScope.GROUP.value
        }:
            raise ValidationError("人设生效范围不合法")
        if "emoji_keys" in payload and not isinstance(payload["emoji_keys"], list):
            raise ValidationError("emoji_keys 必须是数组")
        if "life_schedule" in payload:
            schedule = payload["life_schedule"]
            if not isinstance(schedule, list):
                raise ValidationError("生活作息必须是数组")
            cleaned: list[dict[str, str]] = []
            for item in schedule:
                if not isinstance(item, dict):
                    raise ValidationError("生活作息项格式不合法")
                start, end, activity = (
                    str(item.get("start", "")).strip(),
                    str(item.get("end", "")).strip(),
                    str(item.get("activity", "")).strip(),
                )
                if not (start or end or activity):
                    continue
                if not (_CLOCK.match(start) and _CLOCK.match(end)) or not activity:
                    raise ValidationError("生活作息需包含 HH:MM 起止时间和活动内容")
                if len(activity) > 60:
                    raise ValidationError("作息活动内容不能超过 60 字")
                cleaned.append({"start": start, "end": end, "activity": activity})
            payload["life_schedule"] = cleaned
        if "style_settings" in payload:
            settings = payload["style_settings"]
            if not isinstance(settings, dict) or set(settings) - DEFAULT_STYLE_SETTINGS.keys():
                raise ValidationError("人设参数格式不合法或包含未知参数")
            for key, value in settings.items():
                if key == "style":
                    valid = isinstance(value, str) and value in _STYLE_NAMES
                elif key == "topic_fallback":
                    valid = type(value) is bool
                else:
                    minimum, maximum = (20, 2000) if key == "reply_max_chars" else (0, 100)
                    valid = type(value) is int and minimum <= value <= maximum
                if not valid:
                    raise ValidationError(f"人设参数 {key} 的取值不合法")
        if creating:
            payload["style_settings"] = {**DEFAULT_STYLE_SETTINGS, **payload.get("style_settings", {})}
            if "life_schedule" not in payload:
                payload["life_schedule"] = [dict(item) for item in DEFAULT_LIFE_SCHEDULE]
        return payload
