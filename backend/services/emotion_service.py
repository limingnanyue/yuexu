"""情感系统（V1.4）：每段关系一份持续演化的情感状态。

设计要点：
- ``EmotionState`` 以 (bot_id, target_type, target_id) 隔离，与记忆库同构；
- 读取时惰性衰减：心情效价 / 能量随时间向中性回归，超过一天的情绪细节淡出，
  好感与信任是长期量不衰减；无需额外定时任务；
- 每轮对话后（后台异步）用 LLM 输出增量更新（emotion.mode=llm，默认），
  失败或关闭时回退关键词启发式，增量均有边界，避免单轮跳变；
- Prompt 注入：把心情、关系温度、当前动态组织为「你此刻的状态」段落；
- 内心想法：解析回复尾部的 ((想：……)) 独白，剥离后仅存档，不发给用户。
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.character_defaults import DEFAULT_LIFE_SCHEDULE
from backend.common.logger import get_logger
from backend.common.utils import now, truncate
from backend.core.config_loader import get_config
from backend.database.models import Character, EmotionState

logger = get_logger("yuexu.service.emotion")

# 心情向中性回归的半衰期：6h 效价归零、12h 能量回 0.5
_VALENCE_HALF_LIFE = timedelta(hours=6)
_ENERGY_HALF_LIFE = timedelta(hours=12)
# 情绪细节保留期：超过后视为" yesterday 的情绪已经过去"
_DETAIL_TTL = timedelta(hours=24)
# 动态背景保留期：之后回退到作息表推导
_ACTIVITY_TTL = timedelta(hours=4)

_AFFECTION_BOUNDS = (-5.0, 5.0)
_TRUST_BOUNDS = (-3.0, 3.0)

MOOD_LABELS = {
    "positive": "开心", "calm": "平静", "low": "低落", "irritated": "烦躁",
    "excited": "兴奋", "touched": "感动", "worried": "担心", "bored": "无聊",
}

# 启发式兜底：口语正面 / 负面 / 生气 / 悲伤信号
_POSITIVE = re.compile(
    r"开心|高兴|太好了|不错|厉害|牛|爱你|喜欢你|哈哈|笑死|感谢|谢谢|好消息|成功|升|中奖|舒服|爽"
)
_NEGATIVE = re.compile(
    r"难过|伤心|难受|烦|累|压力|崩溃|失望|糟糕|倒霉|倒霉|生气|气死|讨厌|滚|闭嘴|无聊|emo|哭"
)
_AFFECTION_UP = re.compile(r"爱你|喜欢你|想你|最好的|有你真好|多亏你|谢谢你")
_AFFECTION_DOWN = re.compile(r"滚|闭嘴|讨厌你|烦死你|别理我|不想理你|拉黑")

UPDATE_PROMPT = """你是拟人聊天角色的情感状态引擎。根据这轮对话，更新角色对这位朋友的情感状态。

当前状态：
{state}

用户说：{user_text}
角色回复：{bot_text}

只输出 JSON，不要解释、不要 Markdown 代码块：
{{"mood_label":"一个词：开心/平静/低落/烦躁/兴奋/感动/担心/无聊","mood_valence":-1到1的小数,"mood_energy":0到1的小数,"affection_delta":-5到5的整数,"trust_delta":-3到3的整数,"mood_note":"此刻内心的第一人称一句话，20字内","last_event":"本轮最触动情绪的一件事，20字内，没有触动就留空","current_activity":"结合作息、当前动态与对话推断此刻在干嘛，15字内；没有变化输出 keep","inner_thought":"角色这轮没说出口的内心想法，30字内，用第一人称"}}

规则：
1. 情绪有连续性，在当前状态基础上小幅演化，不要每轮剧变；
2. 平常寒暄所有增量给 0，mood_label 沿用或归为平静；
3. affection_delta / trust_delta 只在有明确好感或反感信号时非 0；
4. inner_thought 是藏在心里没说的话，不是回复内容的复述；
5. 不要输出 JSON 以外的任何内容。"""


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _half_life_decay(value: float, target: float, elapsed: timedelta, half_life: timedelta) -> float:
    if elapsed <= timedelta(0) or half_life <= timedelta(0):
        return value
    factor = 0.5 ** (elapsed.total_seconds() / half_life.total_seconds())
    return target + (value - target) * factor


def relationship_stage(affection: float) -> str:
    if affection >= 85:
        return "挚友"
    if affection >= 65:
        return "好朋友"
    if affection >= 45:
        return "熟人"
    if affection >= 25:
        return "认识"
    return "初识"


def current_schedule_activity(life_schedule: list | None, moment=None) -> str:
    """按生活作息推导「现在大概在干嘛」；未配置时用默认作息兜底。"""
    items = life_schedule or DEFAULT_LIFE_SCHEDULE
    moment = moment or now()
    minutes = moment.hour * 60 + moment.minute
    for item in items:
        if not isinstance(item, dict):
            continue
        start, end = str(item.get("start", "")), str(item.get("end", ""))
        activity = str(item.get("activity", "")).strip()
        if not start or not end or not activity:
            continue
        start_minutes = _parse_clock(start)
        end_minutes = _parse_clock(end)
        if start_minutes is None or end_minutes is None:
            continue
        if start_minutes <= minutes < end_minutes:
            return activity
    return ""


def _parse_clock(text: str) -> int | None:
    match = re.match(r"^(\d{1,2}):(\d{1,2})$", text.strip())
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if not (0 <= hour <= 24 and 0 <= minute < 60):
        return None
    return hour * 60 + minute


def parse_inner_thought(text: str) -> tuple[str, str]:
    """剥离回复中的内心独白，返回 (对外文本, 内心想法)。

    支持格式：((想：……))、（(想:……)）、（想：……）；未闭合时截到行尾。
    """
    if not text:
        return text, ""
    thoughts: list[str] = []

    def _collect(match: re.Match) -> str:
        content = (match.group(1) or match.group(2) or "").strip()
        if content:
            thoughts.append(content)
        return ""

    text = re.sub(
        r"[(（]{2}\s*想\s*[:：]\s*(.*?)[)）]{2}|（想\s*[:：]\s*(.*?)）",
        _collect, text, flags=re.DOTALL,
    )
    if not thoughts:
        # 未闭合 / 变体：整行以 (想 / ((想 开头时截掉
        match = re.search(r"[(（]{1,2}\s*想\s*[:：].*$", text, flags=re.DOTALL)
        if match:
            content = match.group(0)
            content = re.sub(r"^[((（]{1,2}\s*想\s*[:：]\s*", "", content).strip()
            content = re.sub(r"[))）]{1,2}\s*$", "", content).strip()
            if content:
                thoughts.append(content)
            text = text[:match.start()].rstrip()
    text = re.sub(r"\s*[(（]{2}[^()（）]{0,40}[)）]{2}\s*", " ", text).strip()
    return text.strip(), " / ".join(thoughts)[:255]


class EmotionService:
    """情感状态管理与 Prompt 注入。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.config = get_config()

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    async def get_or_create(
        self,
        bot_id: str,
        *,
        user_id: str = "",
        group_id: str | None = None,
        scene: str = "private",
        character_id: str | None = None,
    ) -> EmotionState:
        """按 (bot, target) 维度取情感状态，读取时完成惰性衰减。"""
        target_type = "group" if scene == "group" and group_id else "user"
        target_id = group_id or "" if target_type == "group" else user_id
        conditions = [
            EmotionState.bot_id == bot_id,
            EmotionState.target_type == target_type,
            EmotionState.target_id == target_id,
        ]
        state = await self.session.scalar(select(EmotionState).where(*conditions).limit(1))
        if state is None:
            state = EmotionState(
                bot_id=bot_id,
                target_type=target_type,
                target_id=target_id,
                group_id=group_id if target_type == "group" else None,
                user_id=user_id,
                character_id=character_id,
            )
            self.session.add(state)
            try:
                async with self.session.begin_nested():
                    await self.session.flush()
            except IntegrityError:
                # 并发消息同时建档：以先入库者为准
                await self.session.rollback()
                state = await self.session.scalar(select(EmotionState).where(*conditions).limit(1))
            return state
        self._apply_decay(state)
        return state

    def _apply_decay(self, state: EmotionState) -> None:
        moment = now()
        elapsed = moment - state.updated_at if state.updated_at else timedelta(0)
        if elapsed < timedelta(minutes=5):
            return
        state.mood_valence = round(
            _clamp(_half_life_decay(state.mood_valence, 0.0, elapsed, _VALENCE_HALF_LIFE), -1.0, 1.0), 3
        )
        state.mood_energy = round(
            _clamp(_half_life_decay(state.mood_energy, 0.5, elapsed, _ENERGY_HALF_LIFE), 0.0, 1.0), 3
        )
        if elapsed >= _DETAIL_TTL:
            state.mood_note = ""
            state.last_event = ""
            if state.mood_valence == 0.0 and abs(state.mood_energy - 0.5) < 0.02:
                state.mood_label = "平静"
        if elapsed >= _ACTIVITY_TTL:
            # 动态背景过期后回退作息推导，由注入时计算，这里只清空旧值
            state.current_activity = ""

    # ------------------------------------------------------------------
    # Prompt 注入
    # ------------------------------------------------------------------
    def build_prompt_section(
        self,
        state: EmotionState | None,
        character: Character | None,
        *,
        scene: str = "private",
    ) -> str:
        if state is None:
            return ""
        from backend.services.character_service import CharacterService  # 局部导入避免环

        settings = CharacterService.get_style_settings(character) if character else {}
        moment = now()
        activity = state.current_activity or current_schedule_activity(
            character.life_schedule if character else None, moment
        )
        lines = ["【你此刻的状态与情感】（真实感受，自然体现在语气里，绝不直接报告数字）"]
        mood = f"- 此刻心情：{state.mood_label}"
        if state.mood_note:
            mood += f"——{state.mood_note}"
        lines.append(mood)
        if scene == "group":
            lines.append(
                f"- 对这个群的氛围：好感 {state.affection:.0f}/100，整体 {relationship_stage(state.affection)} 阶段"
            )
        else:
            stage = relationship_stage(state.affection)
            lines.append(
                f"- 对这位朋友：好感 {state.affection:.0f}/100（{stage}），信任 {state.trust:.0f}/100，"
                f"已经聊过 {state.interaction_count} 轮；"
                + ("已经相当熟络，说话随意亲近，可以有只属于你们的默契和玩笑"
                   if state.affection >= 65 else
                   "慢慢熟起来了，可以更放松一些" if state.affection >= 45 else
                   "还不算太熟，友好但保持一点分寸感")
            )
        if activity:
            lines.append(f"- 你现在正在：{activity}")
        if state.last_event:
            lines.append(f"- 最近让你有触动的事：{state.last_event}")
        # 情绪连带：心情差 / 能量低时语气放缓收住玩笑；效价高时更有活力
        if state.mood_valence <= -0.3:
            lines.append("- 你自己心情也不好，语气自然低一点，不强行活泼，但不用向对方诉苦")
        elif state.mood_valence >= 0.4 and state.mood_energy >= 0.6:
            lines.append("- 你此刻挺有精神的，语气可以更轻快")
        empathy = int(settings.get("empathy", 80))
        if empathy >= 60:
            lines.append("- 对方的情绪变化你会在意：对方低落时收住玩笑先接情绪，开心时真心跟着高兴")
        initiative = int(settings.get("initiative", 40))
        if initiative > 0:
            lines.append(
                f"- 你有自己的生活和想法（倾向 {initiative}%）：聊天时可以自然带出你正在做的事、"
                "最近的感受、对话题的真实观点，像朋友分享而不是汇报；频率是倾向不是指标，不要每轮都用"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------
    async def update_after_exchange(
        self,
        bot_id: str,
        *,
        user_id: str = "",
        group_id: str | None = None,
        scene: str = "private",
        character_snapshot: dict[str, Any] | None = None,
        user_text: str,
        bot_text: str,
        inner_thought: str = "",
    ) -> EmotionState | None:
        """一轮对话后演化情感状态；失败静默，不影响主链路。

        ``character_snapshot`` 为 {"style_settings": dict, "life_schedule": list}
        的纯数据快照，允许跨数据库会话传递（后台任务独立开 session）。
        """
        if not bool(self.config.get("emotion.enabled", True)):
            return None
        snapshot = character_snapshot or {}
        try:
            state = await self.get_or_create(
                bot_id, user_id=user_id, group_id=group_id, scene=scene,
            )
            schedule = snapshot.get("life_schedule") or None
            result = await self._update_with_llm(
                state, user_text, bot_text, schedule=schedule,
            )
            if result is None:
                result = self._heuristic_update(state, user_text)
            self._finalize_update(state, result, schedule=schedule)
            if inner_thought.strip():
                state.last_inner_thought = truncate(inner_thought.strip(), 255)
            await self.session.commit()
            return state
        except Exception:  # noqa: BLE001 - 情感更新属于旁路，不抛错
            logger.exception("情感状态更新失败：%s/%s", bot_id, user_id or group_id)
            await self.session.rollback()
            return None

    def _finalize_update(
        self, state: EmotionState, result: dict[str, Any], *, schedule: list | None = None,
    ) -> None:
        # 好感 / 信任为长期量（不随时间衰减），只按每轮增量演化；
        # 单轮增量先夹到 ±5 / ±3（LLM 与启发式结果之外的最终防线），累计值夹在 0-100
        affection_delta = _clamp(float(result.get("affection_delta", 0.0)), *_AFFECTION_BOUNDS)
        trust_delta = _clamp(float(result.get("trust_delta", 0.0)), *_TRUST_BOUNDS)
        state.affection = round(_clamp(float(state.affection) + affection_delta, 0.0, 100.0), 2)
        state.trust = round(_clamp(float(state.trust) + trust_delta, 0.0, 100.0), 2)
        state.mood_valence = round(_clamp(float(result.get("mood_valence", state.mood_valence)), -1.0, 1.0), 3)
        state.mood_energy = round(_clamp(float(result.get("mood_energy", state.mood_energy)), 0.0, 1.0), 3)
        label = str(result.get("mood_label") or "").strip()
        state.mood_label = truncate(label, 32) if label else state.mood_label
        note = str(result.get("mood_note") or "").strip()
        state.mood_note = truncate(note, 255)
        event = str(result.get("last_event") or "").strip()
        if event:
            state.last_event = truncate(event, 255)
        thought = str(result.get("inner_thought") or "").strip()
        if thought:
            state.last_inner_thought = truncate(thought, 255)
        activity = str(result.get("current_activity") or "").strip()
        if activity and activity != "keep":
            state.current_activity = truncate(activity, 128)
        elif not activity and not state.current_activity:
            # 没有动态时回填作息推导；schedule 为空时自动使用默认作息
            state.current_activity = current_schedule_activity(schedule)
        state.interaction_count += 1
        state.last_message_at = now()
        state.updated_at = now()

    async def _update_with_llm(
        self,
        state: EmotionState,
        user_text: str,
        bot_text: str,
        *,
        schedule: list | None,
    ) -> dict[str, Any] | None:
        if str(self.config.get("emotion.mode", "llm")).lower() != "llm":
            return None
        try:
            from backend.services.llm_service import LLMService  # 局部导入避免环

            llm = LLMService(self.session)
            model = await llm.resolve_model(state.bot_id)
            if model is None:
                return None
            state_json = json.dumps(
                {
                    "心情": state.mood_label,
                    "效价": state.mood_valence,
                    "能量": state.mood_energy,
                    "好感": state.affection,
                    "信任": state.trust,
                    "最近触动": state.last_event,
                    "当前动态": state.current_activity or current_schedule_activity(schedule),
                },
                ensure_ascii=False,
            )
            reply = await asyncio.wait_for(
                llm.chat(
                    [
                        {"role": "system", "content": UPDATE_PROMPT.format(
                            state=state_json,
                            user_text=truncate(user_text, 400),
                            bot_text=truncate(bot_text, 400),
                        )},
                        {"role": "user", "content": "请输出 JSON。"},
                    ],
                    model=model,
                    temperature=0.3,
                    max_tokens=300,
                ),
                timeout=max(1.0, float(self.config.get("emotion.update_timeout", 10))),
            )
            if not reply.success:
                return None
            return self._parse_update_json(reply.content)
        except asyncio.TimeoutError:
            logger.debug("情感更新 LLM 超时，回退启发式")
            return None
        except Exception:  # noqa: BLE001
            logger.debug("情感更新 LLM 失败，回退启发式", exc_info=True)
            return None

    @staticmethod
    def _parse_update_json(raw: str) -> dict[str, Any] | None:
        match = re.search(r"\{.*\}", raw or "", re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        result: dict[str, Any] = {}
        try:
            result["mood_valence"] = _clamp(float(data.get("mood_valence", 0)), -1.0, 1.0)
            result["mood_energy"] = _clamp(float(data.get("mood_energy", 0.5)), 0.0, 1.0)
            result["affection_delta"] = _clamp(
                float(data.get("affection_delta", 0)), *_AFFECTION_BOUNDS
            )
            result["trust_delta"] = _clamp(float(data.get("trust_delta", 0)), *_TRUST_BOUNDS)
        except (TypeError, ValueError):
            return None
        for key in ("mood_label", "mood_note", "last_event", "current_activity", "inner_thought"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                result[key] = value.strip()
        return result

    def _heuristic_update(self, state: EmotionState, user_text: str) -> dict[str, Any]:
        """关键词启发式：LLM 不可用时的最小可用演化。"""
        positive, negative = bool(_POSITIVE.search(user_text)), bool(_NEGATIVE.search(user_text))
        if positive and not negative:
            mood, valence, delta = MOOD_LABELS["positive"], min(1.0, state.mood_valence + 0.3), 1.0
        elif negative and not positive:
            if re.search(r"气死|生气|滚|闭嘴|烦死", user_text):
                mood, valence, delta = MOOD_LABELS["irritated"], max(-1.0, state.mood_valence - 0.4), -2.0
            elif re.search(r"难过|伤心|哭|emo|崩溃|失望", user_text):
                mood, valence, delta = MOOD_LABELS["low"], max(-1.0, state.mood_valence - 0.4), 0.0
            else:
                mood, valence, delta = MOOD_LABELS["low"], max(-1.0, state.mood_valence - 0.25), 0.0
        else:
            mood, valence, delta = state.mood_label, state.mood_valence, 0.0
        result = {"mood_label": mood, "mood_valence": valence, "mood_energy": state.mood_energy}
        if _AFFECTION_UP.search(user_text):
            result["affection_delta"] = 2.0
        elif _AFFECTION_DOWN.search(user_text):
            result["affection_delta"] = max(_AFFECTION_BOUNDS[0], delta - 3.0)
        elif delta:
            result["affection_delta"] = delta
        return result

    # ------------------------------------------------------------------
    # 后台管理
    # ------------------------------------------------------------------
    async def list_page(
        self, page: int = 1, page_size: int = 20, keyword: str | None = None,
    ) -> tuple[list[EmotionState], int]:
        conditions = []
        if keyword:
            lowered = keyword.lower()
            conditions.append(or_(
                EmotionState.user_id.contains(lowered),
                EmotionState.target_id.contains(lowered),
                EmotionState.mood_label.contains(lowered),
            ))
        stmt = select(EmotionState).order_by(EmotionState.updated_at.desc())
        if conditions:
            stmt = stmt.where(*conditions)
        total = int(await self.session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
        states = list((await self.session.scalars(
            stmt.offset((page - 1) * page_size).limit(page_size)
        )).all())
        for state in states:
            self._apply_decay(state)
        return states, total

    async def get_by_id(self, state_id: str) -> EmotionState:
        state = await self.session.get(EmotionState, state_id)
        if not state:
            from backend.common.exceptions import NotFoundError

            raise NotFoundError("情感状态不存在")
        return state

    async def adjust(self, state_id: str, data: dict[str, Any]) -> EmotionState:
        """后台手动校准情感状态。"""
        state = await self.get_by_id(state_id)
        if "mood_label" in data and str(data["mood_label"]).strip():
            state.mood_label = truncate(str(data["mood_label"]).strip(), 32)
        if "mood_note" in data:
            state.mood_note = truncate(str(data["mood_note"] or "").strip(), 255)
        if "affection" in data:
            state.affection = _clamp(float(data["affection"]), 0.0, 100.0)
        if "trust" in data:
            state.trust = _clamp(float(data["trust"]), 0.0, 100.0)
        if "current_activity" in data:
            state.current_activity = truncate(str(data["current_activity"] or "").strip(), 128)
        if "last_event" in data:
            state.last_event = truncate(str(data["last_event"] or "").strip(), 255)
        state.updated_at = now()
        await self.session.flush()
        return state

    async def reset(self, state_id: str) -> None:
        state = await self.get_by_id(state_id)
        await self.session.delete(state)
        await self.session.flush()

    async def clear_all(self) -> int:
        result = await self.session.execute(delete(EmotionState))
        return int(result.rowcount or 0)
