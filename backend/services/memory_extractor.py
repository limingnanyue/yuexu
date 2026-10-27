"""长期记忆抽取：LLM 摘要提纯优先，规则抽取兜底。"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Iterator

from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.constants import MemoryType
from backend.common.logger import get_logger
from backend.common.utils import clean_text, extract_keywords, now_iso
from backend.services.memory_support import NOISE_PATTERN

logger = get_logger("yuexu.memory.extractor")
MAX_FACTS_PER_CHUNK = 8

# (正则, 旧分类, 记忆类型, 置信度, 取第几个分组)
_FACT_RULES: tuple[tuple[re.Pattern[str], str, str, float, int], ...] = (
    (re.compile(r"我叫([^\s，。！？,!?]{1,20})"), "profile", "fact", 0.85, 0),
    (re.compile(r"我的名字是([^\s，。！？,!?]{1,20})"), "profile", "fact", 0.85, 0),
    (re.compile(r"我是([^\s，。！？,!?]{1,20})"), "profile", "fact", 0.7, 0),
    (re.compile(r"我今年([0-9一二三四五六七八九十]{1,3})岁"), "profile", "fact", 0.8, 0),
    (re.compile(r"我住在([^\s，。！？,!?]{1,20})"), "profile", "fact", 0.8, 0),
    (re.compile(r"我的生日是([^\s，。！？,!?]{1,20})"), "profile", "fact", 0.9, 0),
    (re.compile(r"我(?:很)?喜欢([^\s，。！？,!?]{1,30})"), "preference", "preference", 0.75, 0),
    (re.compile(r"我(?:很)?讨厌([^\s，。！？,!?]{1,30})"), "preference", "preference", 0.75, 0),
    (re.compile(r"我不喜欢([^\s，。！？,!?]{1,30})"), "preference", "preference", 0.75, 0),
    (re.compile(r"(?:我)?(?:打算|计划|准备)([^。！？!?]{2,40})"), "plan", "plan", 0.7, 0),
    (re.compile(r"记住[，,:：]?(.{2,60})"), "explicit", "fact", 0.95, 1),
)

# shortcut: 规则仅兜底明确的第一人称心情与已发生经历，扩展口语覆盖时补充对应样例。
_PERSONAL_TIME = r"(?:\d{4}[-年/]\d{1,2}[-月/]\d{1,2}日?|今天|昨天|前天|昨晚|今晚|今早|早上|上午|下午|晚上|最近|这几天|上周|上个月|刚刚|刚才|刚|现在|目前|那天)"
_PERSONAL_MOOD = re.compile(
    rf"^(?:{_PERSONAL_TIME})?我(?:{_PERSONAL_TIME})?(?:因为.{{1,60}})?"
    r"(?:感觉|觉得|心情)?(?:有点|有些|很|挺|特别|非常|好|超级|真的|不太)?"
    r"(?:开心|高兴|难过|伤心|低落|焦虑|紧张|委屈|失落|烦躁|生气|孤独|疲惫|累|无聊|emo|压力很大|心情不错|心情不好)",
    re.IGNORECASE,
)
_PERSONAL_EXPERIENCE = re.compile(
    rf"^(?:{_PERSONAL_TIME})?我(?:{_PERSONAL_TIME})?(?:和.{{1,12}})?"
    r"(?:去(?:了|过)?.{2,60}|(?:吃了|喝了|买了|看了|见了|做了|收到(?:了)?|完成(?:了)?|参加(?:了)?|捡到(?:了)?|学会(?:了)?|找到(?:了)?).{1,60}"
    r"|(?:下班|加班|失眠|散步|跑步|考试|搬家)(?:了|过)?.{0,60})$"
)
_INTEREST_TIME = rf"(?:{_PERSONAL_TIME}|明年|今年|明天|后天|下周|下个月|春天|夏天|秋天|冬天|\d{{1,2}}月\d{{1,2}}(?:日|号))"
_PERSONAL_INTEREST_RULES = (
    (re.compile(
        rf"^(?:{_INTEREST_TIME})?我(?:{_INTEREST_TIME})?"
        r"(?:(?:一直|真的|很|特别|好|还|也|又)?(?:想吃|想去).+|的(?:心愿|愿望)是.+)$"
    ), "wish"),
    (re.compile(
        rf"^(?:{_INTEREST_TIME})?我(?:{_INTEREST_TIME})?"
        r"(?:有点|很|特别|一直|最|也)?(?:担心|在意).+$"
    ), "concern"),
)
_RULE_QUESTION = re.compile(
    r"(?:吗|么|呢)$|什么(?!都)|谁|哪(?:里|儿|个|些|种|位|天|年|月)|(?:怎么|如何|几岁|多少)$|还是|是不是"
)

EXTRACT_PROMPT = """你是长期记忆抽取器。从用户这句话里提取值得长期记住的独立事实。

只输出 JSON 数组，不要解释、不要 Markdown 代码块。格式：
[{"content":"独立事实，不超过60字","type":"fact|preference|plan","category":"fact|preference|plan|emotion|experience|wish|concern","confidence":0.0-1.0,"keywords":["关键词"]}]

规则：
1. 保留第一人称的身份、偏好、计划，也记住有语义的心情、情绪、碎碎念和日常小事、经历；
2. 忽略纯寒暄、重复语气词、无信息噪声、假设、提问和他人的经历，不从助手回复编造记忆；
3. 每条只表达一个事实，改写为简洁陈述句；每段最多8条，独立事件不要因数量过少而遗漏；
4. 用户明确要求“记住”的内容必须保留，置信度 1.0；
5. 情绪用 category=emotion，日常经历用 category=experience，type 都为 fact；保留用户的时间信息和事件原因，结合当前记录日期理解“今天/昨天”，不得推断为永久性格或长期偏好；
6. 第一人称明确说想吃、想去、心愿用 category=wish，担心、在意的事项用 category=concern，type 都为 fact；这两类保留完整原话和已有时间，不添加日期、不编造细节，不提取假设、提问或他人的心愿和在意事项；
7. 没有可记忆内容时返回空数组 []。"""


def manual_fact(content: str) -> dict[str, Any]:
    """手动 /remember 内容做类型推断，置信度固定为 1。"""
    text = re.sub(r"^[/／]remember\s*", "", content, flags=re.I).strip()
    memory_type = MemoryType.FACT.value
    if re.search(r"(喜欢|讨厌|偏好|爱吃|爱听|害怕|不喜欢)", text):
        memory_type = MemoryType.PREFERENCE.value
    elif re.search(r"(打算|计划|准备|下周|明天|下个月|生日)", text):
        memory_type = MemoryType.PLAN.value
    return {
        "content": text,
        "category": "explicit",
        "memory_type": memory_type,
        "confidence": 1.0,
        "fuzzy_weight": 0.0,
        "keywords": extract_keywords(text, limit=6),
    }


def extract_by_rules(text: str, *, record_date: str | None = None) -> list[dict[str, Any]]:
    """规则抽取第一人称事实：显式“记住”优先进整句，其余按标点拆句。"""
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()
    interests: list[tuple[str, str]] = []

    def append_fact(fact: str, category: str, memory_type: str, confidence: float) -> None:
        if category in {"emotion", "experience"}:
            fact = f"记录日期 {record_date or now_iso()[:10]}：{fact}"
        fact = clean_text(fact, 120).strip("，。！？,.!? ")
        if not fact or fact in seen or len(facts) >= MAX_FACTS_PER_CHUNK:
            return
        seen.add(fact)
        facts.append(
            {
                "content": fact,
                "category": category,
                "memory_type": memory_type,
                "confidence": confidence,
                "fuzzy_weight": 0.05,
                "keywords": extract_keywords(fact, limit=6),
            }
        )

    # shortcut: 规则保守跳过引述、疑问和条件句，复杂混合语义交给 LLM 抽取。
    explicit_pattern, explicit_category, explicit_type, explicit_confidence, group_index = _FACT_RULES[-1]
    statements: list[str] = []
    for block in re.findall(r"[^。！？!?\n]+[。！？!?]?", text):
        statement = block.strip().rstrip("。！？!?").strip()
        if (
            block.rstrip().endswith(("?", "？"))
            or re.search(r"(?:吗|么|呢)$", statement)
            or re.search(r"如果|假如|假设|要是|比如|例如", statement)
            or re.search(r"^[^，,；;]*(?:说|问|写道|提到|表示|示例)[：:，,]", statement)
            or NOISE_PATTERN.search(statement)
        ):
            continue
        request = re.sub(r"^(?:请(?:你|帮我)?|帮我|你要|你)\s*", "", statement)
        match = explicit_pattern.match(request)
        if match:
            fact = match.group(group_index)
            unquoted_fact = re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*"', "", fact)
            if not _RULE_QUESTION.search(unquoted_fact):
                append_fact(fact, explicit_category, explicit_type, explicit_confidence)
        statements.append(re.sub(
            r'(^|[：:，,]|说|问|写道)\s*(?:“[^”]*”|「[^」]*」|『[^』]*』|"[^"\n]*")',
            r"\1", statement,
        ))

    for sentence in (fragment.strip() for statement in statements for fragment in re.split(r"[，,；;]", statement)):
        if not (2 <= len(sentence) <= 140) or _RULE_QUESTION.search(sentence):
            continue
        fact_sentence = re.sub(rf"^{_INTEREST_TIME}", "", sentence)
        for pattern, category, memory_type, confidence, _group_index in _FACT_RULES[:-1]:
            match = pattern.match(fact_sentence)
            if not match:
                continue
            if re.match(r"怎么|如何|几岁|多少", match.group(1)):
                break
            append_fact(match.group(0), category, memory_type, confidence)
            break
        else:
            if _PERSONAL_MOOD.search(sentence):
                append_fact(sentence, "emotion", "fact", 0.75)
            elif _PERSONAL_EXPERIENCE.search(sentence) and (
                re.search(_PERSONAL_TIME, sentence) or re.search(r"了|过|已经", sentence)
            ):
                append_fact(sentence, "experience", "fact", 0.75)
            elif not re.search(r"(?:想吃|想去)(?:什么|哪)|(?:担心|在意)(?:什么|谁)", sentence):
                for pattern, category in _PERSONAL_INTEREST_RULES:
                    if pattern.fullmatch(sentence):
                        interests.append((sentence, category))
                        break
    # 显式记忆、偏好和计划优先，心愿和关切共用每段上限。
    for sentence, category in interests:
        append_fact(sentence, category, "fact", 0.75)
    return facts[:MAX_FACTS_PER_CHUNK]


def parse_llm_facts(
    raw: str, *, record_date: str | None = None, strict_extraction: bool = False,
) -> list[dict[str, Any]]:
    """解析 LLM 返回的 JSON 数组，容忍代码块 / 额外文字。"""
    match = re.search(r"\[.*\]", raw or "", re.S)
    if not match:
        if strict_extraction:
            raise ValueError("记忆提取未返回 JSON 数组")
        return []
    try:
        data = json.loads(match.group(0))
    except (TypeError, ValueError):
        if strict_extraction:
            raise
        return []
    if strict_extraction and any(not isinstance(item, dict) or not isinstance(item.get("content"), str)
                                 or not item["content"].strip() for item in data):
        raise ValueError("记忆提取事实格式无效")
    facts: list[dict[str, Any]] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        content = clean_text(str(item.get("content") or ""), 120)
        if not content or NOISE_PATTERN.search(content):
            continue
        memory_type = str(item.get("type") or "fact").lower()
        if memory_type not in {"fact", "preference", "plan"}:
            memory_type = "fact"
        category = str(item.get("category") or memory_type).lower()
        if category not in {"profile", "fact", "preference", "plan", "explicit", "emotion", "experience", "wish", "concern"}:
            category = memory_type
        if category in {"wish", "concern"}:
            memory_type = "fact"
        if category in {"emotion", "experience"}:
            memory_type = "fact"
            if not re.match(r"^记录日期 \d{4}-\d{2}-\d{2}[：:]", content):
                content = clean_text(f"记录日期 {record_date or now_iso()[:10]}：{content}", 120)
        try:
            confidence = float(item.get("confidence", 0.8))
        except (TypeError, ValueError):
            confidence = 0.8
        keywords = item.get("keywords")
        facts.append(
            {
                "content": content,
                "category": category,
                "memory_type": memory_type,
                "confidence": min(1.0, max(0.3, confidence)),
                "fuzzy_weight": 0.1,
                "keywords": (
                    [str(keyword) for keyword in keywords if str(keyword).strip()][:8]
                    if isinstance(keywords, list)
                    else extract_keywords(content, limit=6)
                ),
            }
        )
    return facts[:MAX_FACTS_PER_CHUNK]


async def extract_with_llm(
    session: AsyncSession,
    text: str,
    *,
    bot_id: str,
    group_id: str | None,
    timeout: float = 8.0,
    record_date: str | None = None,
    strict_extraction: bool = False,
    llm: Any | None = None,
    model: Any | None = None,
) -> list[dict[str, Any]]:
    """单段文本的 LLM 抽取；可复用外部已解析的模型 / LLMService。

    ``llm`` / ``model`` 由 ``extract_facts`` 的并行路径传入：模型解析（3 级
    覆盖的数据库查询）只做一次，各分段的 ``chat`` 并发执行。``LLMService.chat``
    在传入 model 后不再访问数据库，因此共享同一个 service 是安全的。
    """
    try:
        from backend.services.llm_service import LLMService

        llm = llm or LLMService(session)
        model = model if model is not None else await llm.resolve_model(bot_id, group_id)
        if model is None:
            if strict_extraction:
                raise RuntimeError("记忆提取模型不可用")
            return []
        reply = await asyncio.wait_for(
            llm.chat(
                [
                    {"role": "system", "content": EXTRACT_PROMPT + f"\n当前记录日期：{record_date or now_iso()[:10]}。"},
                    {"role": "user", "content": text},
                ],
                model=model,
                temperature=0.1,
                max_tokens=1600,
            ),
            timeout=max(1.0, timeout),
        )
        if not reply.success:
            if strict_extraction:
                raise RuntimeError("记忆提取模型调用失败")
            return []
        # 新事项只收原话里明确存在的第一人称陈述，模型改写失败时由规则兜底。
        interests = {(fact["category"], fact["content"]) for fact in extract_by_rules(text, record_date=record_date)
                     if fact["category"] in {"wish", "concern"}}
        return [fact for fact in parse_llm_facts(reply.content, record_date=record_date, strict_extraction=strict_extraction)
                if fact["category"] not in {"wish", "concern"}
                or (fact["category"], fact["content"]) in interests]
    except Exception:  # noqa: BLE001 - 抽取失败回退规则
        if strict_extraction:
            raise
        logger.debug("LLM 记忆抽取失败，回退规则", exc_info=True)
        return []


# 单次抽取请求的输入上限：约两千字一段（软上限），超过硬上限的超长单句
# 会被强制切开，避免一整段无标点长文本被当成一个「句子」塞进模型请求。
_EXTRACT_CHUNK_CHARS = 2000
_EXTRACT_CHUNK_HARD_LIMIT = 4000


def _split_long_sentence(sentence: str, limit: int) -> list[str]:
    """把超长无标点文本按就近的空白 / 逗号 / 分号切开，兜底按长度硬切。

    只在「整段都没有句末标点」时使用（粘贴的日志、代码、URL 列表、未闭合
    引号导致的连续文本）。切点尽量落在分隔符之后，尽量不切断完整语义。
    """
    pieces: list[str] = []
    start = 0
    while start < len(sentence):
        end = min(len(sentence), start + limit)
        if end < len(sentence):
            cut = max(
                sentence.rfind(separator, start + limit // 2, end)
                for separator in ("\n", "，", ",", "；", ";", " ", "\t")
            )
            if cut > start:
                end = cut + 1  # 分隔符归前一段，保持片段可读
        pieces.append(sentence[start:end])
        start = end
    return [piece for piece in pieces if piece]


def _extraction_chunks(text: str) -> Iterator[str]:
    """约两千字一段，保留完整句与引述，避免将假设后半句误存为事实。

    边界识别：只在「引号之外」的句末标点处切分。旧实现有个漏洞——一旦出现
    未闭合的引号（用户粘贴对话、代码、引号不平衡）或整段没有句末标点，
    边界集合就只剩结尾一个位置，于是整段文本（可能是几十 KB）被当成一个
    分片发给模型：输入无上限、费用与超时风险都不可控。

    这里补两道上限：
    - 累积片段超过 ``_EXTRACT_CHUNK_CHARS`` 立即切分（与原来一致）；
    - 单句超过 ``_EXTRACT_CHUNK_HARD_LIMIT`` 时按分隔符硬切，保证单次请求
      的输入长度有界。

    同时改用列表缓冲 + ``"".join``，避免旧实现 ``chunk += sentence`` 在循环里
    反复复制已累积内容（每个分片 O(句数²) 的字符复制）。
    """
    quote_ends = {"“": "”", "「": "」", "『": "』", '"': '"'}
    quotes: list[str] = []
    boundaries: list[int] = []
    for index, char in enumerate(text):
        if quotes and char == quotes[-1]:
            quotes.pop()
        elif char in quote_ends:
            quotes.append(quote_ends[char])
        if char in "。！？!?\n" and not quotes:
            boundaries.append(index + 1)
    boundaries.append(len(text))
    start = 0
    parts: list[str] = []
    size = 0
    for end in boundaries:
        sentence = text[start:end]
        start = end
        if not sentence:
            continue
        # 超长「单句」：先按分隔符硬切，逐片送入上面的软上限逻辑
        pieces = (
            _split_long_sentence(sentence, _EXTRACT_CHUNK_HARD_LIMIT)
            if len(sentence) > _EXTRACT_CHUNK_HARD_LIMIT else [sentence]
        )
        for piece in pieces:
            if parts and size + len(piece) > _EXTRACT_CHUNK_CHARS:
                yield "".join(parts)
                parts, size = [], 0
            parts.append(piece)
            size += len(piece)
    if parts:
        yield "".join(parts)


async def extract_facts(
    session: AsyncSession,
    text: str,
    *,
    bot_id: str,
    group_id: str | None,
    llm_enabled: bool = True,
    timeout: float = 8.0,
    record_date: str | None = None,
    strict_extraction: bool = False,
    llm_concurrency: int = 1,
) -> list[dict[str, Any]]:
    """分段抽取事实；长文本可并发调用模型，缩短后台写入等待。

    旧实现逐段串行调用 LLM：10 段 × 8s 超时最坏要 80s，用户下一轮对话
    可能已经结束，记忆还没落库。这里在 ``llm_concurrency>1`` 且确实有多段
    时，先解析一次模型，再用信号量限制并发（默认 2，避免把服务商限流打满）。
    各段结果按原始顺序合并，事实去重口径与串行路径完全一致。

    单段 / 关闭 LLM 时仍走原路径，便于规则兜底与测试替身复用。
    """
    chunks = list(_extraction_chunks(text))
    facts: list[dict[str, Any]] = []
    seen: set[str] = set()

    def merge(chunk: str, extracted: list[dict[str, Any]]) -> None:
        # LLM 有结果时以 LLM 为准；失败 / 空结果回退规则，保持旧行为。
        for fact in extracted or extract_by_rules(chunk, record_date=record_date):
            if fact["content"] not in seen:
                seen.add(fact["content"])
                facts.append(fact)

    concurrency = max(1, int(llm_concurrency))
    if llm_enabled and concurrency > 1 and len(chunks) > 1:
        try:
            from backend.services.llm_service import LLMService

            llm = LLMService(session)
            model = await llm.resolve_model(bot_id, group_id)
        except Exception:  # noqa: BLE001 - 模型解析失败退回串行 / 规则
            if strict_extraction:
                raise
            model = None
            llm = None
        if model is not None and llm is not None:
            semaphore = asyncio.Semaphore(concurrency)

            async def run(chunk: str) -> list[dict[str, Any]]:
                async with semaphore:
                    return await extract_with_llm(
                        session, chunk, bot_id=bot_id, group_id=group_id,
                        timeout=timeout, record_date=record_date,
                        strict_extraction=strict_extraction, llm=llm, model=model,
                    )

            # gather 保持输入顺序；strict_extraction 的异常会直接向上抛，
            # 由恢复任务记录失败，不会静默写入半套事实。
            extracted_chunks = await asyncio.gather(*(run(chunk) for chunk in chunks))
            for chunk, extracted in zip(chunks, extracted_chunks, strict=True):
                merge(chunk, extracted)
            return facts

    for chunk in chunks:
        extracted = []
        if llm_enabled:
            extracted = await extract_with_llm(
                session, chunk, bot_id=bot_id, group_id=group_id, timeout=timeout,
                record_date=record_date, strict_extraction=strict_extraction,
            )
        merge(chunk, extracted)
    return facts
