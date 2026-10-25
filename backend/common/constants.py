"""全局枚举与常量：禁止在业务模块内硬编码字符串。"""

from __future__ import annotations

from enum import StrEnum


class Platform(StrEnum):
    """适配平台类型。"""

    QQ = "qq"
    WECHAT = "wechat"
    QQ_BOT = "qq_bot"
    WECHAT_CLAWBOT = "wechat_clawbot"


PLATFORM_LABELS: dict[str, str] = {
    Platform.QQ.value: "QQ 个人账号",
    Platform.WECHAT.value: "微信个人账号",
    Platform.QQ_BOT.value: "QQ 官方机器人",
    Platform.WECHAT_CLAWBOT.value: "微信 ClawBot",
}


class AccountStatus(StrEnum):
    """机器人账号在线状态。"""

    OFFLINE = "offline"          # 未登录 / 已下线
    WAITING_QR = "waiting_qr"    # 等待扫码
    SCANNING = "scanning"        # 已扫码待确认
    CONNECTING = "connecting"    # 连接中
    ONLINE = "online"            # 在线
    RISK = "risk"                # 风控异常
    ERROR = "error"              # 连接失败


ACCOUNT_STATUS_LABELS: dict[str, str] = {
    AccountStatus.OFFLINE.value: "离线",
    AccountStatus.WAITING_QR.value: "等待扫码",
    AccountStatus.SCANNING.value: "已扫码",
    AccountStatus.CONNECTING.value: "连接中",
    AccountStatus.ONLINE.value: "在线",
    AccountStatus.RISK.value: "风控异常",
    AccountStatus.ERROR.value: "连接失败",
}


class MessageScene(StrEnum):
    """消息场景。"""

    PRIVATE = "private"
    GROUP = "group"


class SegmentType(StrEnum):
    """统一消息段类型（可扩展）。"""

    TEXT = "text"
    EMOJI = "emoji"
    VOICE = "voice"
    IMAGE = "image"
    VIDEO = "video"
    AT = "at"
    REPLY = "reply"
    FACE = "face"


class TriggerType(StrEnum):
    """自动推送任务触发类型。"""

    DELAY = "delay"        # 一次性延时
    CRON = "cron"          # 定时定点
    INTERVAL = "interval"  # 循环周期


class PushTarget(StrEnum):
    """推送目标类型。"""

    GROUP = "group"
    PRIVATE = "private"


class Role(StrEnum):
    """后台账号角色。"""

    OWNER = "owner"    # 超级主人
    ADMIN = "admin"    # 管理员
    USER = "user"      # 普通用户


class CharacterScope(StrEnum):
    """人设生效范围。"""

    ALL = "all"
    PRIVATE = "private"
    GROUP = "group"


class MemoryScope(StrEnum):
    """长期记忆作用域。"""

    PRIVATE = "private"
    GROUP = "group"


class MemoryMode(StrEnum):
    """记忆检索模式（4.5.4）。"""

    PRECISE = "precise"
    FUZZY = "fuzzy"


class MemoryTier(StrEnum):
    """冷热记忆分层（4.5.3）。"""

    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class MemoryType(StrEnum):
    """记忆类型（4.5.2）。"""

    FACT = "fact"
    PREFERENCE = "preference"
    PLAN = "plan"


class SearchTrigger(StrEnum):
    """搜索触发方式。"""

    AUTO = "auto"
    COMMAND = "command"


class LogModule(StrEnum):
    """日志模块分类。"""

    MESSAGE = "message"
    AI = "ai"
    SEARCH = "search"
    PUSH = "push"
    SYSTEM = "system"
    ACCOUNT = "account"


class LogLevel(StrEnum):
    """结构化日志级别。"""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


# ---------------------------------------------------------------------------
# 会话 Key 规则（开发文档 4.6）
# ---------------------------------------------------------------------------

def private_session_key(bot_id: str, user_id: str) -> str:
    """私聊会话 key：ctx:private:{bot_id}:{user_id}"""
    return f"ctx:private:{bot_id}:{user_id}"


def group_session_key(bot_id: str, group_id: str, user_id: str) -> str:
    """群聊会话 key：ctx:group:{bot_id}:{group_id}:{user_id}"""
    return f"ctx:group:{bot_id}:{group_id}:{user_id}"


CONTEXT_KEY_PATTERN = "ctx:*"


# ---------------------------------------------------------------------------
# 限流 Key 规则
# ---------------------------------------------------------------------------

def rate_user_key(bot_id: str, user_id: str) -> str:
    return f"rate:user:{bot_id}:{user_id}"


def rate_group_key(bot_id: str, group_id: str) -> str:
    return f"rate:group:{bot_id}:{group_id}"


def rate_account_key(bot_id: str) -> str:
    return f"rate:account:{bot_id}"


def rate_voice_key(bot_id: str, target_id: str) -> str:
    return f"rate:voice:{bot_id}:{target_id}"


def push_daily_key(task_id: str) -> str:
    from datetime import datetime

    return f"push:daily:{task_id}:{datetime.now():%Y%m%d}"


# ---------------------------------------------------------------------------
# 默认值
# ---------------------------------------------------------------------------

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200
DEFAULT_CONTEXT_TTL_SECONDS = 600
DEFAULT_CONTEXT_MAX_ROUNDS = 20

# 意图 / 指令前缀
COMMAND_PREFIX = "/"
CMD_CLEAR_CONTEXT = "/clearctx"
CMD_SEARCH = "/search"
CMD_REMEMBER = "/remember"
CMD_FORGET = "/forget"
CMD_IMAGE = "/image"
CMD_DRAW = "/draw"

# 分隔符：群聊唤醒词、@ 判断
WAKEUP_SEPARATORS = (" ", "，", ",", ":", "：", "\u3000")
