"""通用工具：ID、时间、文件、文本、随机延时、深合并等（无业务逻辑）。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import re
import secrets
import unicodedata
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Sequence, TypeVar

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


# ---------------------------------------------------------------------------
# Token 估算（不依赖具体模型的 tokenizer）
# ---------------------------------------------------------------------------
# 主流 BPE 词表里，一个汉字 / 假名 / 谚文基本对应 0.6~1 个 token，英文与数字
# 约 3~4 个字符 1 个 token。旧的上下文窗口校验直接拿 UTF-8 字节数当 token 用
# （一个汉字 3 字节），对中文场景高估约 3 倍：8k 窗口只能留下约 1.7k 字历史，
# 中文长篇对话因此过早触发压缩。这里改用「汉字 1 token、其他字符 0.3 token」
# 的保守估算——对中文仍是安全上界（不会低估导致服务商 400），同时能把窗口
# 真正用起来，历史记忆保留得更多。
_NON_CJK = re.compile(r"[^\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
_OTHER_CHARS_PER_TOKEN = 0.3
# 每条消息除正文外还有角色、分隔符、工具字段等固定开销（保守取 8 token）
MESSAGE_TOKEN_OVERHEAD = 8


def estimate_text_tokens(text: str | None) -> int:
    """粗略估算文本 token 数：汉字 1 token、其他字符 0.3 token。

    只用于上下文窗口与预算估算（``LLMService``），不用于计费；对中文是安全
    上界，对英文略保守，混合文本按字符类型分别累加。
    """
    if not text:
        return 0
    content = str(text)
    # 先去掉非 CJK 字符，剩下的长度就是汉字 / 假名 / 谚文个数
    cjk = len(_NON_CJK.sub("", content))
    return cjk + math.ceil((len(content) - cjk) * _OTHER_CHARS_PER_TOKEN)


def estimate_message_tokens(content: Any) -> int:
    """估算一条 messages 的 token 数：兼容纯文本与多段（文本 + 图片）内容。

    图片按固定上限计价（无法从 URL 推断实际分辨率），保证窗口校验不会因为
    多图请求而低估。
    """
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                total += estimate_text_tokens(str(part.get("text") or ""))
            else:
                total += 1024  # 单张图片的保守估算
        return total + MESSAGE_TOKEN_OVERHEAD
    return estimate_text_tokens("" if content is None else str(content)) + MESSAGE_TOKEN_OVERHEAD


# 关键词提取的通用停用词。这里只放「几乎不携带检索信息」的词，不把
# “喜欢 / 讨厌 / 生日”这类可能承载事实的词去掉；稀有词权重由 IDF 处理。
_KEYWORD_STOPWORDS = frozenset({
    "的", "了", "是", "我", "你", "他", "她", "它", "在", "有", "和", "就",
    "不", "也", "都", "这", "那", "吗", "呢", "啊", "呀", "吧", "一个",
    "什么", "怎么", "怎样", "如何", "为什么", "哪里", "哪儿", "哪个", "哪些",
    "多少", "几岁", "是不是", "有没有", "可以", "能否", "帮我", "告诉", "一下",
    "现在", "最近", "时候", "事情", "东西", "地方", "这个", "那个", "这些",
    "那些", "我们", "你们", "他们", "她们", "它们", "自己", "一些", "还是",
    "就是", "因为", "所以", "但是", "然后", "而且", "如果", "要是", "以及",
    "开头", "结尾", "首先", "最后", "接着", "其实", "只是", "真的", "非常",
    "特别", "比较", "可能", "应该", "需要", "已经", "一直", "有点", "有些",
})

# 纯功能字：一个候选词如果全部由这些字组成（“我的 / 这个 / 什么”），
# 即使不在停用词表里也删掉；保留“名字 / 杭州 / 火锅”等含实字的候选。
# 对 2 字词采用更严格的口径：只要含功能字就丢弃（“你还 / 字吗 / 的生”），
# 因为两个字里有一个虚词时，检索区分度通常已经很低；3/4 字短语仍允许
# 含虚词，以保留“我的生日 / 上次说的”这类完整语义。
_KEYWORD_FUNCTION_CHARS = frozenset(
    "的了是我你他她它在有和就不也都这那吗呢啊呀吧么什怎哪里哪个些着过被把给让对从向于为以"
    "还得很太更最会能要又只跟"
)
_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{1,}")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")


def _informative_keyword(word: str) -> bool:
    """过滤纯停用词 / 纯功能字；返回 True 表示值得作为检索 token。"""
    if not word or word in _KEYWORD_STOPWORDS:
        return False
    return any(char not in _KEYWORD_FUNCTION_CHARS for char in word)


def _keyword_quality(word: str) -> bool:
    """按词长采用不同信噪比门槛，减少“你还 / 字吗”这类高频噪声。

    - 2 字词：不能含功能字（“火锅 / 生日 / 名字 / 猫咪”保留）；
    - 3/4 字词：至少两个实字（“我的生日 / 五月十号”保留）。
    """
    if not _informative_keyword(word):
        return False
    if len(word) == 2:
        return all(char not in _KEYWORD_FUNCTION_CHARS for char in word)
    if len(word) >= 3:
        return sum(char not in _KEYWORD_FUNCTION_CHARS for char in word) >= 2
    return True


def _keyword_size_quotas(total: int) -> dict[int, int]:
    """把关键词名额分配给 4/3/2 字切片。

    旧实现按 4→3→2 顺序取前 N 个，长句只有开头几个词能进入关键词，句尾
    的专名（住址、店名、宠物名）经常丢失。这里给 2 字词更大配额（中文里
    最稳的检索单位），同时保留少量 4 字短语表达完整语义。
    """
    if total <= 0:
        return {4: 0, 3: 0, 2: 0}
    weights = {4: 0.25, 3: 0.30, 2: 0.45}
    raw = {size: total * weight for size, weight in weights.items()}
    quotas = {size: int(value) for size, value in raw.items()}
    remainder = total - sum(quotas.values())
    for size in sorted(weights, key=lambda item: raw[item] - quotas[item], reverse=True)[:remainder]:
        quotas[size] += 1
    return quotas


def _pick_evenly(candidates: list[tuple[int, str]], count: int) -> list[tuple[int, str]]:
    """从按出现位置排序的候选里均匀取样，保证句首和句尾都有机会入选。"""
    if count <= 0 or not candidates:
        return []
    if len(candidates) <= count:
        return list(candidates)
    if count == 1:
        return [candidates[len(candidates) // 2]]
    step = (len(candidates) - 1) / (count - 1)
    picked: list[tuple[int, str]] = []
    last_index = -1
    for index in range(count):
        position = round(index * step)
        if position <= last_index:
            position = last_index + 1
        if position >= len(candidates):
            break
        picked.append(candidates[position])
        last_index = position
    return picked


@lru_cache(maxsize=2048)
def _extract_keywords_cached(text: str, limit: int) -> tuple[str, ...]:
    """关键词提取的纯函数实现（带 LRU：同一记忆/查询会被索引和召回重复处理）。

    算法：
    1. 英文/型号词按完整单词保留；
    2. 中文按连续汉字段生成 4/3/2 字候选，过滤停用词和纯功能字；
    3. 每种长度按出现位置均匀取样，最后按出现顺序输出。

    均匀取样的关键作用是消除“长句只看开头”的偏差；2 字词配额保证
    “火锅 / 杭州 / 团子”这类核心实体不会被长短语挤掉。
    """
    if not text or limit <= 0:
        return ()

    selected: list[tuple[int, str]] = []
    seen: set[str] = set()

    def add(position: int, word: str) -> None:
        if word and word not in seen:
            seen.add(word)
            selected.append((position, word))

    # 英文单词 / 模型名优先：它们通常信息量高，且不会被中文切片规则影响。
    for match in _LATIN_WORD.finditer(text):
        if len(selected) >= limit:
            return tuple(word for _position, word in selected[:limit])
        add(match.start(), match.group().lower())

    # 中文候选按「长度 → 位置」收集。使用 dict 去重并保留首次出现位置。
    per_size: dict[int, dict[str, int]] = {4: {}, 3: {}, 2: {}}
    all_candidates: list[tuple[int, str]] = []
    for run in _CJK_RUN.finditer(text):
        chunk = run.group()
        # 单字查询（“猫”“花”）没有 2-4 字切片，单独保留实字，否则检索为空。
        if len(chunk) == 1:
            if _informative_keyword(chunk):
                add(run.start(), chunk)
            continue
        for size in (4, 3, 2):
            for offset in range(len(chunk) - size + 1):
                word = chunk[offset : offset + size]
                if not _keyword_quality(word):
                    continue
                position = run.start() + offset
                per_size[size].setdefault(word, position)
                all_candidates.append((position, word))

    remaining = max(0, limit - len(selected))
    quotas = _keyword_size_quotas(remaining)
    for size in (4, 3, 2):
        candidates = sorted(
            ((position, word) for word, position in per_size[size].items()),
            key=lambda item: item[0],
        )
        for position, word in _pick_evenly(candidates, quotas[size]):
            add(position, word)

    # 短文本某一长度候选不足时，用其余候选补满；仍然按位置取样，避免
    # 因为某个长度缺失而只返回句首关键词。
    if len(selected) < limit:
        for position, word in sorted(all_candidates, key=lambda item: (item[0], -len(item[1]))):
            if len(selected) >= limit:
                break
            add(position, word)

    selected.sort(key=lambda item: (item[0], -len(item[1])))
    return tuple(word for _position, word in selected[:limit])


def extract_keywords(text: str, limit: int = 6) -> list[str]:
    """轻量关键词提取（中文 2-4 字切片 + 英文单词，带停用词过滤）。

    结果用于关键词兜底召回、查询扩展和记忆标签。返回的是新列表，调用方
    可以安全修改；内部 LRU 缓存保存 tuple，避免重复处理长记忆。
    """
    if not text:
        return []
    return list(_extract_keywords_cached(str(text), max(1, int(limit))))


@lru_cache(maxsize=1024)
def _extract_query_keywords_cached(text: str, limit: int) -> tuple[str, ...]:
    """查询专用关键词：优先输出全部“内容二字词”，再补充 3/4 字短语。

    检索查询通常很短，但“它叫什么名字”这类句子里的关键实体（名字 / 猫）
    经常被长短语和虚词挤掉。内容二字词是中文最稳的匹配单位：这里把所有
    不含功能字的相邻二字词都收进查询集合（例如“我的生日是五月十号”会得到
    生日 / 五月 / 月十 / 十号），再叠加少量长短语做精确加分。

    上限比 ``limit`` 略宽（最多 28 个），因为关键词覆盖率打分能处理重叠
    切片，SQL LIKE 候选圈选也能承受；返回结果仍去重并保持文本顺序。
    """
    if not text or limit <= 0:
        return ()

    max_total = min(28, max(limit * 2, 18))
    selected: list[tuple[int, str]] = []
    seen: set[str] = set()
    lowered = text.lower()

    def add(position: int, word: str) -> None:
        if word and word not in seen:
            seen.add(word)
            selected.append((max(0, position), word))

    for match in _LATIN_WORD.finditer(text):
        add(match.start(), match.group().lower())

    # 第一优先级：全部内容二字词（过滤功能字 / 停用词），覆盖句首到句尾。
    for run in _CJK_RUN.finditer(text):
        chunk = run.group()
        if len(chunk) == 1:
            if _informative_keyword(chunk):
                add(run.start(), chunk)
            continue
        for offset in range(len(chunk) - 1):
            word = chunk[offset : offset + 2]
            if _keyword_quality(word):
                add(run.start() + offset, word)

    # 第二优先级：长短语用于“原句命中”加分；如果内容二字词已经占满名额，
    # 长短语可以舍弃（覆盖率仍由二字词保证）。
    for word in _extract_keywords_cached(text, max(6, limit)):
        if len(selected) >= max_total:
            break
        add(lowered.find(word), word)

    selected.sort(key=lambda item: (item[0], -len(item[1])))
    return tuple(word for _position, word in selected[:max_total])


def extract_query_keywords(text: str, limit: int = 12) -> list[str]:
    """提取检索查询关键词（内容二字词优先，长短语补充）。

    与 ``extract_keywords`` 的区别：后者偏向“少量代表性标签”，本函数偏向
    “尽量不漏实体”，专门供召回、关键词兜底和重排使用。
    """
    if not text:
        return []
    return list(_extract_query_keywords_cached(str(text), max(1, int(limit))))


class KeywordQuery:
    """一次查询的预计算词法剖析（关键词位置 + IDF 权重）。

    同一个查询通常要对多个候选记忆打分：关键词兜底召回（SQL LIKE 圈出的几十
    条）、向量候选重排（MMR 之前的全部命中）、模糊模式双路召回。旧实现每打分
    一次就重新 ``re.sub`` 规范化查询、重新 casefold 关键词集合、再对每个关键词
    重新 ``str.find``——候选越多、问题越长，重复的无用功越多。

    这里把「与候选无关」的部分一次算好：规范化查询、每个关键词在查询里的位置、
    被关键词覆盖的字符权重总和。``score()`` 只剩两件事——判定关键词是否出现在
    候选里、按字符累加命中的最高权重。打分口径与升级前逐位一致（每个字符只取
    覆盖它的最高 IDF 权重；查询原文整体命中再 +0.2），只是把重复计算移出循环。
    """

    __slots__ = ("_original_bonus", "normalized", "query", "terms", "total")

    def __init__(
        self,
        query: str,
        keywords: Sequence[str],
        *,
        idf: dict[str, float] | None = None,
    ) -> None:
        self.query = query or ""
        # 与旧实现一致：去掉全部空白后按小写匹配（中文没有大小写差异）
        self.normalized = re.sub(r"\s+", "", self.query.lower())
        weights = idf or {}
        terms: list[tuple[str, int, int, float]] = []
        covered: dict[int, float] = {}
        for keyword in {str(item).casefold() for item in keywords if str(item).strip()}:
            start = self.normalized.find(keyword)
            if start < 0:
                continue
            weight = float(weights.get(keyword, 1.0))
            end = start + len(keyword)
            terms.append((keyword, start, end, weight))
            for offset in range(start, end):
                if weight > covered.get(offset, 0.0):
                    covered[offset] = weight
        self.terms = tuple(terms)
        # 查询侧的总权重：分母固定，不随候选变化，因此可以预先算好
        self.total = sum(covered.values())
        # 原句命中加分只在查询不短于 3 个字时启用（与旧实现一致）
        self._original_bonus = len(self.normalized) >= 3

    def score(self, content: str) -> float:
        """按预计算好的查询剖析给一条候选记忆打分（0~1）。"""
        if not self.normalized or not self.terms or self.total <= 0:
            return 0.0
        haystack = (content or "").casefold()
        if not haystack:
            return 0.0
        # 每个字符只按「覆盖它的最高权重」计一次：重叠的 2/3/4 字切片不会把
        # 一次长词命中重复放大（与旧实现逐字符取 max 的结果完全一致）。
        best: dict[int, float] = {}
        for keyword, start, end, weight in self.terms:
            if keyword not in haystack:
                continue
            for offset in range(start, end):
                if weight > best.get(offset, 0.0):
                    best[offset] = weight
        if not best:
            return 0.0
        score = sum(best.values()) / self.total
        if self._original_bonus and self.normalized in haystack:
            # 查询原文整体出现在记忆里（长笔记中的原句）：最强的词法证据
            score = min(1.0, score + 0.2)
        return min(1.0, score)


def keyword_idf(
    documents: Iterable[str], keywords: Iterable[str]
) -> dict[str, float]:
    """候选文档集上的平滑 IDF：``log((N+1)/(df+1)) + 1``。

    关键词检索的候选通常由 SQL LIKE 圈出；在该候选集上统计文档频率，可以
    低成本区分「条条记忆都有」的泛词与只出现在少数记忆里的专名，供覆盖率
    打分加权。语料为空时返回 1.0（等价于不加权）。
    """
    corpus = [str(item or "").casefold() for item in documents]
    total = max(1, len(corpus))
    idf: dict[str, float] = {}
    for keyword in {str(item).casefold() for item in keywords if str(item).strip()}:
        frequency = sum(1 for content in corpus if keyword in content)
        idf[keyword] = math.log((total + 1) / (frequency + 1)) + 1.0
    return idf


def keyword_coverage(
    query: str,
    content: str,
    keywords: Sequence[str],
    *,
    idf: dict[str, float] | None = None,
    profile: "KeywordQuery | None" = None,
) -> float:
    """关键词覆盖率（0~1）：查询关键词有多少（按 IDF 加权）真正出现在记忆里。

    相比「命中个数 / 固定 3」，这里解决两个问题：

    1. 中文关键词是 2/3/4 字重叠切片，直接数命中个数会让同一段文字被重复
       计分（命中一个四字词往往连带命中它的多个 2/3 字子串）；这里按查询
       字符位置取并集，每个字符只按覆盖它的最高 IDF 计一次权重。
    2. 通用词（「我」「喜欢」）与专有词（「橘猫」「杭州」）区分度不同，
       由 ``keyword_idf`` 传入候选集统计的 IDF，稀有词命中权重更大。

    查询原文整体出现在记忆中（长笔记里的原句）时额外加分——这是最强的
    词法证据。返回值恒在 0~1，供关键词兜底召回、模糊模式双路召回与重排共用。

    需要在同一查询上给多个候选打分时（召回 / 重排 / 查重），先在循环外构造
    ``KeywordQuery`` 并通过 ``profile`` 传入，可省掉每个候选一次查询规范化
    与关键词定位；单次调用不传 ``profile``，行为与旧接口完全一致。
    """
    query_profile = profile if profile is not None else KeywordQuery(query, keywords, idf=idf)
    return query_profile.score(content)


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
