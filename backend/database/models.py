"""ORM 表模型（只描述数据结构，不包含业务逻辑）。

约定：
- 主键统一为短字符串 ID（``acc_xxx`` / ``char_xxx``），便于日志与接口透传；
- 所有时间字段存本地 naive 时间（个人部署场景，后台直接展示）；
- 账号与人设 / 模型之间使用松散 ID 关联（不建外键），便于配置复制与热切换。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from backend.common.constants import (
    AccountStatus,
    CharacterScope,
    Platform,
    Role,
    TriggerType,
)
from backend.common.utils import new_id


class Base(DeclarativeBase):
    """全局 ORM 基类。"""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, nullable=False
    )


# ---------------------------------------------------------------------------
# 后台用户 / 权限（文档第 7 章）
# ---------------------------------------------------------------------------
class AdminUser(TimestampMixin, Base):
    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("usr_"))
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    role: Mapped[str] = mapped_column(String(16), default=Role.ADMIN.value)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# 机器人账号（文档 4.1）
# ---------------------------------------------------------------------------
class BotAccount(TimestampMixin, Base):
    __tablename__ = "bot_accounts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("acc_"))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), default=Platform.QQ.value)
    account_no: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    adapter_base_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    adapter_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    adapter_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default=AccountStatus.OFFLINE.value)
    character_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # 记忆库独立于登录账号；空值兼容旧库，沿用账号内部 ID 作为存储分区。
    memory_library_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # 单账号开关：{"emoji": true, "voice": false, "search": true, "memory": true, "context": true}
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    auto_connect: Mapped[bool] = mapped_column(Boolean, default=False)
    last_online_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)


# ---------------------------------------------------------------------------
# 独立记忆库：删除连接后仍保留名称和存储分区，便于换号重新绑定。
# ---------------------------------------------------------------------------
class MemoryLibrary(TimestampMixin, Base):
    __tablename__ = "memory_libraries"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[str] = mapped_column(String(16), default="", nullable=False)


# ---------------------------------------------------------------------------
# 拟人角色人设（文档 4.4）
# ---------------------------------------------------------------------------
class Character(TimestampMixin, Base):
    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("char_"))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[str] = mapped_column(Text, default="")
    speaking_style: Mapped[str] = mapped_column(Text, default="")
    background: Mapped[str] = mapped_column(Text, default="")
    # 背景扩展：兴趣爱好 / 社交关系 / 生活作息（按当前时间推导"现在在干嘛"）
    hobbies: Mapped[str] = mapped_column(Text, default="")
    social_circle: Mapped[str] = mapped_column(Text, default="")
    life_schedule: Mapped[list] = mapped_column(JSON, default=list)
    taboos: Mapped[str] = mapped_column(Text, default="")
    red_lines: Mapped[str] = mapped_column(Text, default="")
    system_prompt_template: Mapped[str] = mapped_column(Text, default="")
    style_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    emoji_keys: Mapped[list] = mapped_column(JSON, default=list)
    scope: Mapped[str] = mapped_column(String(16), default=CharacterScope.ALL.value)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# LLM 模型池（文档 4.7）
# ---------------------------------------------------------------------------
class LlmModel(TimestampMixin, Base):
    __tablename__ = "llm_models"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("model_"))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="openai")  # openai 兼容
    base_url: Mapped[str] = mapped_column(String(255), default="https://api.deepseek.com")
    api_key: Mapped[str] = mapped_column(String(255), default="")
    model_name: Mapped[str] = mapped_column(String(128), default="deepseek-chat")
    temperature: Mapped[float] = mapped_column(Float, default=0.8)
    top_p: Mapped[float] = mapped_column(Float, default=1.0)
    max_tokens: Mapped[int] = mapped_column(Integer, default=1024)
    timeout: Mapped[int] = mapped_column(Integer, default=60)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# 群组规则（文档 4.3）
# ---------------------------------------------------------------------------
class GroupRule(TimestampMixin, Base):
    __tablename__ = "group_rules"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("grp_"))
    bot_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    group_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    group_name: Mapped[str] = mapped_column(String(128), default="")
    # 单群独立开关
    enabled_ai: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled_emoji: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled_voice: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled_search: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled_push: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled_memory: Mapped[bool] = mapped_column(Boolean, default=True)
    # 欢迎 / 退群
    welcome_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    welcome_text: Mapped[str] = mapped_column(Text, default="")
    leave_notice: Mapped[str] = mapped_column(Text, default="")
    # 过滤
    block_words: Mapped[list] = mapped_column(JSON, default=list)
    blacklist: Mapped[list] = mapped_column(JSON, default=list)
    # 防刷屏
    anti_flood_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    flood_window_seconds: Mapped[int] = mapped_column(Integer, default=60)
    flood_max_messages: Mapped[int] = mapped_column(Integer, default=8)
    flood_mute_seconds: Mapped[int] = mapped_column(Integer, default=60)
    # 就近覆盖
    character_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_group_rules_bot_group", "bot_id", "group_id"),
    )


# ---------------------------------------------------------------------------
# 表情包库（文档 4.10）
# ---------------------------------------------------------------------------
class EmojiItem(TimestampMixin, Base):
    __tablename__ = "emoji_items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("emo_"))
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    alias: Mapped[str] = mapped_column(String(64), default="")
    category: Mapped[str] = mapped_column(String(32), default="default")
    file_path: Mapped[str] = mapped_column(String(255), default="")
    weight: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# 长期记忆（文档 4.5）
# ---------------------------------------------------------------------------
class ContextSession(TimestampMixin, Base):
    """会话工作快照与原始消息归档；缓存过期不删除此记录。"""

    __tablename__ = "context_sessions"

    session_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    archive: Mapped[list] = mapped_column(JSON, default=list)


class MemoryEntry(TimestampMixin, Base):
    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mem_"))
    bot_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    # 记忆隔离字段（4.5.1）：target_type=user/group，target_id=用户 ID / 群 ID
    target_type: Mapped[str] = mapped_column(String(16), default="user", index=True)
    target_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    scope_type: Mapped[str] = mapped_column(String(16), default="private")
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(32), default="fact")
    # 记忆类型：fact / preference / plan（4.5.2）
    memory_type: Mapped[str] = mapped_column(String(16), default="fact", index=True)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    # 热度 / 置信度 / 模糊权重 / 否定标记（4.5.2 / 4.5.3）
    hot_score: Mapped[float] = mapped_column(Float, default=5.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.7)
    fuzzy_weight: Mapped[float] = mapped_column(Float, default=0.0)
    tag_keywords: Mapped[list] = mapped_column(JSON, default=list)
    rejected: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_memory_scope", "bot_id", "scope_type", "user_id"),
        Index("ix_memory_target", "bot_id", "target_type", "target_id"),
        # 冷记忆淘汰：purge_cold 按 hot_score 极低值圈选，避免全表扫描
        Index("ix_memory_hot", "hot_score"),
        # 全量遍历（游标分批 / 重建索引 / 去重）按 (created_at, id) 有序扫描
        Index("ix_memory_created", "created_at", "id"),
    )


# ---------------------------------------------------------------------------
# 情感系统：每段关系一份持续演化的情感状态（心情 / 好感 / 信任 / 动态）
# ---------------------------------------------------------------------------
class EmotionState(TimestampMixin, Base):
    __tablename__ = "emotion_states"
    __table_args__ = (
        Index("ix_emotion_relation", "bot_id", "target_type", "target_id", unique=True),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("emo_"))
    bot_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    # 与记忆库同构的隔离维度：user / group
    target_type: Mapped[str] = mapped_column(String(16), default="user")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    character_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # 心情：标签 + 效价(-1~1) + 能量(0~1)，读取时惰性向中性回归
    mood_label: Mapped[str] = mapped_column(String(32), default="平静")
    mood_valence: Mapped[float] = mapped_column(Float, default=0.0)
    mood_energy: Mapped[float] = mapped_column(Float, default=0.5)
    mood_note: Mapped[str] = mapped_column(String(255), default="")
    # 关系：好感度 / 信任度 0~100，随互动缓慢演化
    affection: Mapped[float] = mapped_column(Float, default=30.0)
    trust: Mapped[float] = mapped_column(Float, default=30.0)
    interaction_count: Mapped[int] = mapped_column(Integer, default=0)
    # 动态背景：最近触动事件 / 当前在干嘛 / 最近内心想法
    last_event: Mapped[str] = mapped_column(String(255), default="")
    current_activity: Mapped[str] = mapped_column(String(128), default="")
    last_inner_thought: Mapped[str] = mapped_column(String(255), default="")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)



class AutoPushTask(TimestampMixin, Base):
    __tablename__ = "auto_push_tasks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("push_"))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    bot_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), default="group")
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_name: Mapped[str] = mapped_column(String(128), default="")
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {"segments": [...]}
    trigger_type: Mapped[str] = mapped_column(String(16), default=TriggerType.DELAY.value)
    delay_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron_expr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    daily_limit: Mapped[int] = mapped_column(Integer, default=0)
    retry_max: Mapped[int] = mapped_column(Integer, default=2)
    sent_total: Mapped[int] = mapped_column(Integer, default=0)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)


# ---------------------------------------------------------------------------
# 私聊主动惦记（V1.3）
# ---------------------------------------------------------------------------
class UserPushState(TimestampMixin, Base):
    """每个私聊用户的持久开关、随机机会与休眠状态。"""

    __tablename__ = "user_push_state"

    bot_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    chat_type: Mapped[str] = mapped_column(String(16), default="private")
    user_push_switch: Mapped[bool] = mapped_column(Boolean, default=True)
    ignore_count: Mapped[int] = mapped_column(Integer, default=0)
    sleep_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    next_idle_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    idle_attempted: Mapped[bool] = mapped_column(Boolean, default=False)
    last_memory_key: Mapped[str] = mapped_column(String(255), default="")
    next_fallback_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fallback_cooldown_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    claim_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activity_version: Mapped[int] = mapped_column(Integer, default=0)


class UserPushRecord(Base):
    """推送尝试与已读、回复反馈；失败尝试不计入频次。"""

    __tablename__ = "user_push_record"
    __table_args__ = (Index("ix_user_push_frequency", "bot_id", "user_id", "send_time"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    bot_id: Mapped[str] = mapped_column(String(40), nullable=False)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chat_type: Mapped[str] = mapped_column(String(16), default="private")
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False)
    push_content: Mapped[str] = mapped_column(Text, default="")
    send_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    ignore_count: Mapped[int] = mapped_column(Integer, default=0)
    sleep_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    week_push_count: Mapped[int] = mapped_column(Integer, default=0)
    message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sent: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# 活力 Agent：会话活跃度 / 主动搭话日志 / 兜底话题素材库
# ---------------------------------------------------------------------------
class SessionActivity(TimestampMixin, Base):
    """每个会话（机器人 × 私聊/群）的活跃度状态与自适应无聊分阈值。

    唯一键在文档 (target_type, target_id) 基础上增加 bot_id：多账号部署时
    不同机器人对同一用户/群的搭话状态必须相互独立（与记忆/上下文隔离维度一致）。
    """

    __tablename__ = "session_activity"
    __table_args__ = (
        Index(
            "ix_session_activity_target",
            "bot_id", "target_type", "target_id", unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("act_"))
    bot_id: Mapped[str] = mapped_column(String(40), index=True, nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)  # private / group
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    last_msg_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_agent_send_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consecutive_cold_reply: Mapped[int] = mapped_column(Integer, default=0)
    # 当前会话动态无聊分阈值（40-90 锁死，随用户热情度自适应）
    dynamic_threshold: Mapped[int] = mapped_column(Integer, default=60)
    enable_agent: Mapped[bool] = mapped_column(Boolean, default=True)
    is_black: Mapped[bool] = mapped_column(Boolean, default=False)
    hour_send_count: Mapped[int] = mapped_column(Integer, default=0)
    hour_reset_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentActiveLog(Base):
    """活力 Agent 每次尝试 / 发送记录；用户回复后异步回填情绪标签。"""

    __tablename__ = "agent_active_log"
    __table_args__ = (
        Index("ix_agent_active_log_target", "bot_id", "target_type", "target_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True,
    )
    bot_id: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0)
    # 记忆延伸 / 上下文延伸 / 兜底话题
    trigger_reason: Mapped[str] = mapped_column(String(128), default="")
    content: Mapped[str] = mapped_column(Text, default="")
    # success / reject_cooling / reject_black / reject_score_low / reject_limit / reject_window / failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    reject_msg: Mapped[str] = mapped_column(String(128), default="")
    user_reply: Mapped[str] = mapped_column(Text, default="")
    # hot / cold / none（未回填为空串）
    user_reply_sentiment: Mapped[str] = mapped_column(String(16), default="")
    replied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class AgentTopicBank(TimestampMixin, Base):
    """兜底话题素材库：记忆与上下文都没有素材时按权重随机取模板。"""

    __tablename__ = "agent_topic_bank"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("topic_"))
    topic_content: Mapped[str] = mapped_column(Text, nullable=False)
    # normal / memory / fun / question
    tag: Mapped[str] = mapped_column(String(64), default="normal", index=True)
    weight: Mapped[int] = mapped_column(Integer, default=10)
    enable: Mapped[bool] = mapped_column(Boolean, default=True)


# ---------------------------------------------------------------------------
# 日志（文档 4.11 / 6 / 10）
# ---------------------------------------------------------------------------
class MessageLog(Base):
    __tablename__ = "message_logs"
    __table_args__ = (
        Index("ix_message_logs_bot_time", "bot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mlog_"))
    bot_id: Mapped[str] = mapped_column(String(40), index=True, default="")
    platform: Mapped[str] = mapped_column(String(16), default="")
    scene: Mapped[str] = mapped_column(String(16), default="private")
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    direction: Mapped[str] = mapped_column(String(8), default="in")  # in / out
    content: Mapped[str] = mapped_column(Text, default="")
    segments: Mapped[list | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok / blocked / failed
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    memory_processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class AiRequestLog(Base):
    __tablename__ = "ai_request_logs"
    __table_args__ = (
        Index("ix_ai_request_logs_bot_time", "bot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("ailog_"))
    bot_id: Mapped[str] = mapped_column(String(40), index=True, default="")
    scene: Mapped[str] = mapped_column(String(16), default="private")
    group_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    model_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model_name: Mapped[str] = mapped_column(String(128), default="")
    prompt_preview: Mapped[str] = mapped_column(Text, default="")
    response_preview: Mapped[str] = mapped_column(Text, default="")
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class SearchLog(Base):
    __tablename__ = "search_logs"
    __table_args__ = (
        Index("ix_search_logs_bot_time", "bot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("slog_"))
    bot_id: Mapped[str] = mapped_column(String(40), index=True, default="")
    user_id: Mapped[str] = mapped_column(String(64), default="")
    query: Mapped[str] = mapped_column(String(500), default="")
    provider: Mapped[str] = mapped_column(String(32), default="deepseek")
    trigger_mode: Mapped[str] = mapped_column(String(16), default="auto")
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    summary_preview: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class PushLog(Base):
    __tablename__ = "push_logs"
    __table_args__ = (
        Index("ix_push_logs_bot_time", "bot_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("plog_"))
    task_id: Mapped[str] = mapped_column(String(40), index=True, default="")
    bot_id: Mapped[str] = mapped_column(String(40), default="")
    target_type: Mapped[str] = mapped_column(String(16), default="group")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("olog_"))
    level: Mapped[str] = mapped_column(String(16), default="info")
    module: Mapped[str] = mapped_column(String(32), default="system")
    action: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


__all__ = [
    "Base",
    "AdminUser",
    "BotAccount",
    "Character",
    "LlmModel",
    "GroupRule",
    "EmojiItem",
    "MemoryEntry",
    "ContextSession",
    "EmotionState",
    "AutoPushTask",
    "UserPushState",
    "UserPushRecord",
    "SessionActivity",
    "AgentActiveLog",
    "AgentTopicBank",
    "MessageLog",
    "AiRequestLog",
    "SearchLog",
    "PushLog",
    "OperationLog",
]
