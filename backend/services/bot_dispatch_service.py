"""消息分发调度中心（开发文档 4.2）：所有 OneBot 上报消息的唯一入口。

链路顺序：
限流 → 黑名单/屏蔽词/防刷屏 → 固定关键词 → 上下文 → 联网搜索 → 人设
→ 长期记忆 → LLM → 表情/语音解析 → 适配器发送 → 会话写入 → 日志。

新增能力优先通过 ``core.hooks`` 挂载，避免修改主链路。
"""

from __future__ import annotations

import asyncio
import random
import re
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.base_adapter import BaseAdapter, SendResult
from backend.common.constants import (
    CMD_CLEAR_CONTEXT,
    CMD_DRAW,
    CMD_FORGET,
    CMD_IMAGE,
    CMD_REMEMBER,
    CMD_SEARCH,
    LogModule,
    MemoryMode,
    Platform,
    SearchTrigger,
)
from backend.common.exceptions import AdapterError
from backend.common.logger import get_logger
from backend.common.message import BotEvent, MessagePayload, MessageSegment
from backend.common.utils import clean_text, now, now_iso, truncate
from backend.core.background import spawn
from backend.core.config_loader import get_config
from backend.core.hooks import (
    HOOK_EVENT_RECEIVED,
    HOOK_POST_LLM,
    HOOK_POST_SEND,
    HOOK_PRE_LLM,
    HOOK_PRE_SEND,
)
from backend.core.runtime import get_runtime
from backend.database.db import session_scope
from backend.database.models import GroupRule, MessageLog
from backend.repositories.account_repo import AccountRepo
from backend.repositories.log_repo import LogRepo
from backend.services.character_service import CharacterService
from backend.services.context_service import ContextService
from backend.services.emoji_service import EmojiService
from backend.services.emotion_service import EmotionService, parse_inner_thought
from backend.services.group_admin_service import GroupAdminService
from backend.services.image_service import CHAT_IMAGE_PROMPT, SEND_IMAGE_TOOL, ImageService, parse_share_reply
from backend.services.llm_service import LLMService
from backend.services.memory_service import MemoryService
from backend.services.proactive_push_service import ProactivePushService
from backend.services.rate_limit_service import RateLimitService
from backend.services.search_service import SearchResult, SearchService
from backend.services.tts_service import TTSService
from backend.services.vitality_service import VitalityService

logger = get_logger("yuexu.dispatch")


class BotDispatchService:
    """机器人消息分发器。"""

    def __init__(self, session: AsyncSession, adapter: BaseAdapter | None = None) -> None:
        self.session = session
        self.adapter = adapter
        self.config = get_config()
        runtime = get_runtime()
        self.state = runtime.state_manager
        self.factory = runtime.adapter_factory
        self.hooks = runtime.hooks

        self.logs = LogRepo(session)
        self.accounts = AccountRepo(session)
        self.groups = GroupAdminService(session)
        self.contexts = ContextService()
        self.characters = CharacterService(session)
        self.memories = MemoryService(session)
        self.emotion = EmotionService(session)
        self.llm = LLMService(session)
        self.search = SearchService(session)
        self.emojis = EmojiService(session)
        self.tts = TTSService()
        self.images = ImageService()
        self.rate_limit = RateLimitService()
        self.vitality = VitalityService(session)

    # ------------------------------------------------------------------
    # 事件入口
    # ------------------------------------------------------------------
    async def handle_event(self, event: BotEvent) -> None:
        try:
            if event.post_type == "meta_event":
                self.state.heartbeat(event.bot_id)
                return
            if event.post_type == "notice":
                await self._handle_notice(event)
                return
            if event.post_type == "request":
                await self.logs.add_operation(
                    module=LogModule.ACCOUNT.value,
                    action="收到加好友/入群请求",
                    detail=f"{event.user_id} {event.sub_type}",
                )
                return
            if event.post_type != "message":
                return
            await self._handle_message(event)
        except Exception:  # noqa: BLE001 - 分发中心兜底，不中断连接
            logger.exception("消息分发异常：bot=%s message=%s type=%s", event.bot_id, event.message_id, event.post_type)
            try:
                await self.logs.add_operation(
                    level="error",
                    module="dispatch",
                    action="消息处理异常",
                    detail=truncate(event.raw_message, 200),
                )
            except Exception:  # noqa: BLE001
                logger.exception("异常日志写入失败")
            if event.call_id:
                raise

    # ------------------------------------------------------------------
    # 消息处理主链路
    # ------------------------------------------------------------------
    async def _handle_message(self, event: BotEvent) -> None:
        account = await self.accounts.get(event.bot_id)
        if account is None:
            logger.warning("收到未知账号消息：%s", event.bot_id)
            return
        voice_enabled = bool((account.settings or {}).get("voice", True))

        adapter = self._resolve_adapter(account)
        rule = None
        if event.is_group and event.group_id:
            rule = await self.groups.get_rule(event.bot_id, str(event.group_id))

        # 忽略自己发送的消息与空消息
        if event.user_id and event.user_id == event.self_id:
            return
        text = clean_text(event.text, len(event.text))
        if not text and not event.segments:
            return

        # 用户停推与回复反馈先于唤醒开关、限流和模型调用，不能被业务过滤丢弃。
        push_ack = await ProactivePushService(self.session).observe_message(event)
        if push_ack:
            await self._log_inbound(event, text)
            await self._send_text(event, adapter, push_ack)
            return

        # 活力 Agent：未唤醒消息也算会话活跃度；若是对上次主动搭话的回复则回填情绪
        try:
            if self.vitality.enabled:
                await self.vitality.observe_message(event)
        except Exception:  # noqa: BLE001 - 活力观察失败不阻断对话
            logger.debug("活力 Agent 活跃度观察失败", exc_info=True)

        # 是否唤醒机器人（群聊 @ / 唤醒词；私聊默认唤醒）
        if not self._is_triggered(event, text):
            return
        if event.is_group:
            text = self._strip_wakeup(
                text, self.config.get("dispatch.group_keywords", []) or []
            )
        image_parts = []
        # shortcut: 单条消息最多处理 4 张图片/表情，确有批量识图需求时再扩展。
        media = [segment for segment in event.segments if segment.type in {"image", "face"}][:4]
        for segment in media:
            label = segment.content or segment.data.get("summary") or segment.data.get("name")
            if not label:
                label = "[图片/表情包]" if segment.type == "image" else f"[QQ表情 {segment.data.get('id', '')}]"
            text = "\n".join(filter(None, [text, clean_text(str(label), 160)]))
            if segment.type != "image" or not segment.url:
                continue
            try:
                source = urlsplit(segment.url)
                if (source.scheme in {"http", "https"} and source.hostname
                        and not source.username and not source.password
                        and not any(ord(char) < 33 for char in segment.url)):
                    image_parts.append({"type": "image_url", "image_url": {"url": segment.url}})
            except ValueError:
                continue
        if not text:
            return

        if not self._ai_enabled(account.settings, rule):
            return

        # 1. 限流
        allowed, reason = await self.rate_limit.check_message(event)
        if not allowed:
            await self._log_inbound(event, text, status="blocked", error=reason)
            logger.warning("消息被限流：%s", reason)
            return

        # 2. 黑名单 / 屏蔽词 / 防刷屏
        if await self.groups.is_blacklisted(rule, event.user_id):
            await self._log_inbound(event, text, status="blocked", error="命中黑名单")
            return
        blocked_word = await self.groups.match_block_word(rule, text)
        if blocked_word:
            await self._log_inbound(event, text, status="blocked", error=f"命中屏蔽词：{blocked_word}")
            return
        flood_reason = await self.groups.anti_flood(event, rule, adapter)
        if flood_reason:
            await self._log_inbound(event, text, status="blocked", error=flood_reason)
            return

        # 通过基础过滤后记录入站消息（后续版本可改为异步队列批量落库）
        inbound_id = await self._log_inbound(event, text)
        memory_enabled = self.memories.is_enabled(account.settings, rule)
        if not memory_enabled:
            inbound = await self.session.get(MessageLog, inbound_id)
            inbound.memory_processed_at = now()
        await self.session.commit()

        # 3. 指令（/remember、/forget、/clearctx、/search），命中指令后可能继续走 AI
        handled, text, command_search = await self._handle_commands(
            event, text, adapter, memory_enabled=memory_enabled
        )
        if handled:
            return

        # 用户原话已落盘，提取不再依赖模型回复或平台发送是否成功。
        if memory_enabled:
            coro = self._post_memory(event, text, "", log_id=inbound_id)
            if bool(self.config.get("memory.write_async", True)):
                spawn(coro, name=f"yuexu-mem-{event.bot_id}")
            else:
                await coro

        # 上一轮为模糊回忆时，识别用户确认 / 否认并转正或屏蔽
        if memory_enabled and self.config.get("memory.feedback_auto", True):
            await self._apply_memory_feedback(event, text)

        # 固定关键词回复：命中直接返回，跳过 AI
        fixed_reply = self.groups.match_fixed_reply(rule, text)
        if fixed_reply:
            await self._send_text(event, adapter, fixed_reply)
            return

        await self.hooks.emit(HOOK_EVENT_RECEIVED, event=event)

        # 4. 上下文会话
        model = await self.llm.resolve_model(event.bot_id, event.group_id)
        context_budget = self.llm.input_char_budget(
            model, char_cap=int(self.config.get("llm.context_char_budget", 0)),
        )
        use_context = self._context_enabled(account.settings, rule)
        session_data = await self.contexts.get_or_create(event) if use_context else None
        if session_data and session_data.get("frozen"):
            await self._log_inbound(event, text, status="blocked", error="会话已冻结")
            return

        # 5/6/7/8 并行执行：联网搜索（网络耗时最长）∥ 人设解析（DB）∥ 情感状态（DB）
        # ∥ 长期记忆召回（向量）。记忆召回的预算按「搜索资料上限」预留估算：实际
        # 资料只会更短，多余预算由上下文组装自动回收，不会超预算注入。
        async with asyncio.TaskGroup() as preparation:
            search_task: asyncio.Task | None = None
            if command_search is None and self.search.should_search(text, account.settings, rule):
                search_task = preparation.create_task(self._run_auto_search(event, text))
            character_task = preparation.create_task(self._resolve_character(event))
            emotion_task = preparation.create_task(self._get_emotion_state(event))

            # 6. 人设（先等待：预算估算需要 system_prompt 长度）
            character, system_prompt = await character_task
            # 8. 情感状态注入：心情、关系温度、当前动态，随对话持续演化
            emotion_state = await emotion_task
            emotion_section = self.emotion.build_prompt_section(
                emotion_state, character, scene=event.scene.value,
            )
            if emotion_section:
                system_prompt += "\n\n" + emotion_section
            # 自主性触发：按人设「自主表达倾向」的概率，给一次主动分享的机会
            initiative_hint = self._initiative_hint(character, emotion_state)
            if initiative_hint:
                system_prompt += "\n\n" + initiative_hint
            if self._voice_available(event, rule, voice_enabled=voice_enabled):
                system_prompt += (
                    "\n\n【语音发送】当前聊天可将回复文字转为语音发送，系统会按发送策略选择文字或语音；"
                    "自动模式下，长文、代码和链接使用文字，合成失败时回退为文字。"
                    "请直接写要说的话，不要承诺本条一定是语音，不要声称只能打字或不能发语音；"
                    "历史中的[已发送语音]表示语音已成功发送，不要否认。声音由系统合成，不是真人录音。"
                )
            image_enabled = (not event.is_group and event.platform == Platform.QQ
                             and self.images.enabled and self.images.available)

            # 7. 长期记忆召回与搜索并行：双模式召回 + 动态字符预算
            references: list[str] = []
            recall_ids: list[str] = []
            memory_task: asyncio.Task | None = None
            if memory_enabled:
                search_reserve = 0
                if search_task is not None:
                    search_reserve = (
                        int(self.config.get("search.max_summary_chars", 1500)) + 64
                    )
                reference_prompt = system_prompt + ("\n\n" + CHAT_IMAGE_PROMPT if image_enabled else "")
                reference_prompt += "\n\n" + " " * search_reserve if search_reserve else ""
                base_messages = self.contexts.build_messages(
                    session_data, reference_prompt, text,
                    reserve_chars=max(0, int(self.config.get("memory.max_prompt_chars", 900))) + 2,
                    char_budget=context_budget,
                )
                memory_budget = max(
                    0, context_budget - sum(len(item["content"]) for item in base_messages) - 2,
                )
                # 检索查询扩展：携带最近用户发言的关键词，消解「它/这个/什么」类指代
                context_texts = [
                    str(item.get("content") or "")
                    for item in reversed((session_data or {}).get("rounds") or [])
                    if item.get("role") == "user" and item.get("content")
                ][:2]
                memory_task = preparation.create_task(self._recall_memory(
                    bot_id=event.bot_id,
                    target_type="user",
                    target_id=event.user_id,
                    user_id=event.user_id,
                    group_id=event.group_id,
                    scope_type=event.scene.value,
                    query=text,
                    top_k=int(self.config.get("memory.top_k", 5)),
                    prompt_char_budget=memory_budget,
                    context_texts=context_texts,
                ))

            # 5. 等待搜索结果（记忆召回仍在并行执行）
            search_result = command_search
            if search_task is not None:
                search_result = await search_task
            if search_result and search_result.success and self.config.get(
                "llm.inject_search_context", True
            ):
                reference = await self.search.build_reference(search_result)
                if reference:
                    references.append(reference)

            # 7. 等待记忆召回结果
            if memory_task is not None:
                recall_result = await memory_task
                if recall_result.prompt:
                    references.append(recall_result.prompt)
                # 记录本轮召回，供用户“对/不对”反馈时转正或屏蔽，也用于召回热度回馈
                if recall_result.prompt and recall_result.hits:
                    recall_ids = list(recall_result.ids)
                    await self.contexts.set_last_recall(
                        event.session_key(),
                        {
                            "mode": recall_result.mode,
                            "ids": recall_result.ids,
                            "query": truncate(text, 120),
                            "at": now_iso(),
                            "degraded": recall_result.degraded,
                        },
                    )
                else:
                    await self.contexts.clear_last_recall(event.session_key())

        # 8. Prompt 组装
        if references:
            system_prompt = system_prompt + "\n\n" + "\n\n".join(references)
        if image_enabled:
            system_prompt += "\n\n" + CHAT_IMAGE_PROMPT
            if event.call_id:
                system_prompt += "\n当前在语音通话，text会在通话中说出，图片会另发到同一用户的QQ私聊窗口。"

        messages = self.contexts.build_messages(
            session_data if use_context else None, system_prompt, text, char_budget=context_budget,
        )
        if image_parts:
            messages[-1]["content"] = [{"type": "text", "text": messages[-1]["content"]}, *image_parts]

        # 扩展钩子：允许插件改写 Prompt
        pre_results = await self.hooks.emit(
            HOOK_PRE_LLM, event=event, messages=messages, character=character
        )
        for result in pre_results:
            if isinstance(result, dict) and isinstance(result.get("messages"), list):
                messages = result["messages"]

        # 9. LLM
        reply = await self.llm.chat_with_fallback(
            messages, bot_id=event.bot_id, group_id=event.group_id, model=model,
            **({"tools": [SEND_IMAGE_TOOL], "tool_choice": "auto"} if image_enabled else {}),
        )
        reply_text, image_prompt = reply.content, None
        if reply.tool_calls or image_enabled or '"image_prompt"' in reply_text:
            try:
                if reply.tool_calls:
                    if (not image_enabled or len(reply.tool_calls) != 1
                            or reply.tool_calls[0].get("type") != "function"
                            or reply.tool_calls[0].get("function", {}).get("name") != "send_image"):
                        raise ValueError("unexpected image tool call")
                    reply_text = reply.tool_calls[0]["function"]["arguments"]
                reply_text, image_prompt = parse_share_reply(reply_text)
                if reply.tool_calls and not image_prompt:
                    raise ValueError("empty image tool prompt")
            except (ValueError, AttributeError):
                logger.warning("聊天配图决定格式无效，使用文字兜底")
                reply_text, image_prompt = "这次没准备好，换个说法再试试吧", None
        if not image_enabled or not reply.success:
            image_prompt = None
        reply_text = clean_text(reply_text, 4000) or ("" if image_prompt else str(
            self.config.get("dispatch.fallback_reply", "……")
        ))
        # 内心想法：剥离 ((想：……)) 独白，只存档不发出去
        reply_text, inner_thought = parse_inner_thought(reply_text)

        post_results = await self.hooks.emit(
            HOOK_POST_LLM, event=event, reply_text=reply_text, reply=reply
        )
        for result in post_results:
            if isinstance(result, dict) and result.get("reply_text"):
                reply_text = str(result["reply_text"])
        reply_text = re.sub(r"\[已分享AI生成图片[：:][^\]\r\n]*(?:\]|$)", "", reply_text).strip()

        # 10. 表情解析
        emoji_enabled = bool(self.config.get("emoji.enabled", True)) and account.settings.get(
            "emoji", True
        )
        if rule is not None:
            emoji_enabled = emoji_enabled and rule.enabled_emoji
        cleaned_text, emoji_segments = await self.emojis.parse_reply(
            reply_text, character=character, enabled=emoji_enabled,
            max_emojis=self.characters.emoji_limit(reply_text, character),
        )
        cleaned_text = self.characters.constrain_reply(cleaned_text, character)
        emoji_segments = await self.emojis.resolve_segments(emoji_segments)

        # 11. 组装统一分段消息（语音 / 文本 + 表情）
        payload = await self._build_payload(
            event, rule, text=cleaned_text, emoji_segments=emoji_segments,
            voice_enabled=voice_enabled, history=(session_data or {}).get("rounds"),
        )
        if image_prompt:
            image_payload = await self.images.build_share_payload("", image_prompt)
            payload.segments.extend(image_payload.segments)
        if payload.is_empty:
            payload = MessagePayload.from_text(self.characters.constrain_reply(
                str(self.config.get("dispatch.fallback_reply", "……")), character,
            ))

        send_results = await self.hooks.emit(
            HOOK_PRE_SEND, event=event, payload=payload
        )
        for result in send_results:
            if isinstance(result, MessagePayload):
                payload = result
            elif isinstance(result, dict) and result.get("payload"):
                payload = MessagePayload.from_dict(result["payload"])

        # 12. 发送
        sent_payloads: list[MessagePayload] = []
        for bubble in self._reply_payloads(event, payload):
            if not event.call_id:
                await self.rate_limit.random_delay()
            try:
                result = await adapter.reply(event, bubble)
            except AdapterError as exc:
                result = SendResult(success=False, error=str(exc))
            if not result.success:
                logger.warning("消息发送失败：%s", result.error)
                await self._log_outbound(event, bubble, status="failed", error=result.error)
                await self.logs.add_operation(
                    level="error", module="dispatch", action="消息发送失败",
                    detail=str(result.error)[:500],
                )
                fallback_text = "\n".join(
                    segment.content for segment in bubble.segments
                    if segment.type in {"text", "voice"} and segment.content
                )
                if event.platform != Platform.QQ or not fallback_text or not any(
                    segment.type == "voice" for segment in bubble.segments
                ):
                    break
                bubble = MessagePayload.from_text(fallback_text)
                try:
                    result = await adapter.reply(event, bubble)
                except AdapterError as exc:
                    result = SendResult(success=False, error=str(exc))
                if not result.success:
                    logger.warning("语音降级文字发送失败：%s", result.error)
                    await self._log_outbound(event, bubble, status="failed", error=result.error)
                    break
            sent_payloads.append(bubble)
            await self._log_outbound(event, bubble, status="ok")
            await self.hooks.emit(HOOK_POST_SEND, event=event, payload=bubble)

        sent_text = "\n".join(part.text for part in sent_payloads if part.text)
        sent_voice = any(
            segment.type == "voice" for part in sent_payloads for segment in part.segments
        )
        if sent_voice:
            sent_text = "\n".join(
                segment.content for part in sent_payloads for segment in part.segments
                if segment.type == "voice" and segment.content
            ) or cleaned_text or reply_text
        sent_image = image_prompt and any(
            segment.type == "image" and segment.file_path == generated.file_path
            for part in sent_payloads for segment in part.segments
            for generated in image_payload.segments
        )
        if sent_image:
            sent_text = (sent_text + f"\n[已分享AI生成图片：{image_prompt}]").strip()

        # 13. 上下文写入（后台异步，不阻塞回复返回；关键任务队列满时兜底直跑）
        if use_context and sent_text:
            spawn(
                self._post_context(
                    event,
                    text,
                    f"[已发送语音] {sent_text}" if sent_voice else sent_text,
                    char_budget=context_budget,
                ),
                name=f"yuexu-ctx-{event.bot_id}",
                critical=True,
            )

        # 13.1 召回热度回馈（后台异步）：本轮注入的记忆被成功使用后小幅升热，
        # 让「经常被想起」的记忆自然进入热层并提高后续排序；限频在
        # MemoryService.reinforce 内部完成，模型失败时不回馈。
        if (
            reply.success
            and memory_enabled
            and recall_ids
            and self.config.get("memory.recall_reinforce", True)
        ):
            spawn(
                self._post_recall_reinforce(recall_ids, event.bot_id),
                name=f"yuexu-memhit-{event.bot_id}",
            )

        # 15. 情感演化：依据这轮对话更新心情 / 好感 / 信任 / 动态（后台异步）
        if reply.success and emotion_state is not None and sent_text:
            spawn(
                self._post_emotion(
                    event, character, text, sent_text, inner_thought=inner_thought,
                ),
                name=f"yuexu-emo-{event.bot_id}",
            )

        # 15. AI 日志（推理模型的思考过程以【思考】摘要保留在预览里）
        reasoning_prefix = (
            f"【思考】{truncate(reply.reasoning, 160)}\n" if reply.reasoning else ""
        )
        await self.logs.add_ai(
            bot_id=event.bot_id,
            scene=event.scene.value,
            group_id=event.group_id,
            user_id=event.user_id,
            model_id=reply.model_id,
            model_name=reply.model_name,
            prompt_preview=truncate(self._last_user_message(messages), 500),
            response_preview=truncate(reasoning_prefix + reply_text, 500),
            prompt_tokens=reply.prompt_tokens,
            completion_tokens=reply.completion_tokens,
            latency_ms=reply.latency_ms,
            success=reply.success,
            error=truncate(reply.error, 500) if reply.error else None,
        )

    # ------------------------------------------------------------------
    # 指令
    # ------------------------------------------------------------------
    async def _handle_commands(
        self,
        event: BotEvent,
        text: str,
        adapter: BaseAdapter,
        *,
        memory_enabled: bool = True,
    ) -> tuple[bool, str, SearchResult | None]:
        """处理内置指令，返回 (是否已结束, 处理后的文本, 指令搜索结果)。"""
        if not text.startswith("/"):
            return False, text, None

        command = text.split(maxsplit=1)[0]
        if command in {CMD_IMAGE, CMD_DRAW}:
            prompt = text[len(command):].strip()
            if not prompt:
                await self._send_text(event, adapter, "用法：/image 画面描述（也可用 /draw）")
                return True, text, None
            if event.platform in {Platform.QQ_BOT, Platform.WECHAT_CLAWBOT}:
                await self._send_text(event, adapter, "当前通道暂不支持图片发送，请在后台生图页面生成并查看")
                return True, text, None
            if not self.images.enabled or not self.images.available:
                await self._send_text(event, adapter, "生图尚未配置，请先在后台开启并配置生图模型")
                return True, text, None
            generated = await self.images.generate(prompt)
            if not generated["success"]:
                await self._send_text(event, adapter, generated.get("error") or "生图暂时不可用，请稍后重试")
                return True, text, None
            payload = MessagePayload.from_segments([
                MessageSegment.image(file_path=generated["file_path"]),
            ])
            try:
                result = await adapter.reply(event, payload)
                error = None if result.success else result.error or "图片发送失败"
            except AdapterError as exc:
                error = str(exc)
            await self._log_outbound(
                event, payload, status="failed" if error else "ok",
                **({"error": error} if error else {}),
            )
            if error:
                await self._send_text(event, adapter, "图片已生成，但发送失败，请检查通道图片发送配置")
            return True, text, None

        if text.startswith(CMD_REMEMBER):
            content = text[len(CMD_REMEMBER):].strip()
            if not memory_enabled:
                await self._send_text(event, adapter, "记忆功能未开启，请先在后台打开")
                return True, text, None
            if not content:
                await self._send_text(event, adapter, "用法：/remember 需要记住的内容")
                return True, text, None
            entry = await self.memories.remember_manual(event, content)
            await self._send_text(
                event, adapter, "记住啦～" if entry else "这条内容我已经记过了"
            )
            return True, text, None

        if text.startswith(CMD_FORGET):
            keyword = text[len(CMD_FORGET):].strip()
            if not memory_enabled:
                await self._send_text(event, adapter, "记忆功能未开启")
                return True, text, None
            if not keyword:
                await self._send_text(event, adapter, "用法：/forget 要忘记的关键词")
                return True, text, None
            count = await self.memories.forget(event, keyword)
            await self._send_text(
                event,
                adapter,
                f"已忘掉 {count} 条相关记忆" if count else "没有找到相关记忆",
            )
            return True, text, None

        if text.startswith(CMD_CLEAR_CONTEXT):
            await self.contexts.clear(event.session_key())
            await self._send_text(event, adapter, "上下文已清空～")
            return True, text, None

        if text.startswith(CMD_SEARCH):
            query = text[len(CMD_SEARCH):].strip()
            if not query:
                await self._send_text(event, adapter, "用法：/search 你的问题")
                return True, text, None
            if not self.search.is_enabled():
                await self._send_text(event, adapter, "联网搜索尚未开启，请先在后台配置")
                return True, text, None
            result = await self.search.search(
                query,
                trigger_mode=SearchTrigger.COMMAND.value,
                bot_id=event.bot_id,
                user_id=event.user_id,
            )
            if not result.success:
                await self._send_text(event, adapter, "搜索暂时不可用，我先直接回答你吧")
            return False, query, result

        return False, text, None

    # ------------------------------------------------------------------
    # 并行预取（5/6/7/8 步：搜索 ∥ 人设 ∥ 情感 ∥ 记忆召回）
    # ------------------------------------------------------------------
    async def _recall_memory(self, **kwargs: Any) -> Any:
        # 召回超时会使查询连接失效，独立会话避免连带破坏发送日志事务。
        async with AsyncSession(bind=self.session.bind, expire_on_commit=False) as session:
            memories = MemoryService(session, cache=self.memories.cache)
            memories.config = self.memories.config
            return await memories.recall(**kwargs)

    async def _get_emotion_state(self, event: BotEvent) -> Any | None:
        """并行预取本段关系的情感状态；关闭或失败时返回 None。"""
        if not bool(self.config.get("emotion.enabled", True)):
            return None
        try:
            return await self.emotion.get_or_create(
                event.bot_id,
                user_id=event.user_id,
                group_id=event.group_id,
                scene=event.scene.value,
            )
        except Exception:  # noqa: BLE001 - 情感缺失不阻断对话
            logger.exception("情感状态读取失败")
            return None

    @staticmethod
    def _initiative_hint(character: Any | None, emotion_state: Any | None) -> str:
        """按人设「自主表达倾向」低频给一次主动分享机会，其余轮次正常接话。"""
        if character is None or emotion_state is None:
            return ""
        initiative = int(CharacterService.get_style_settings(character).get("initiative", 40))
        if initiative <= 0 or random.random() >= initiative / 200:
            return ""
        return (
            "【本轮主动性机会】这一轮你可以自然带出一件你自己的事、一个突然想到的话题，"
            "或对刚才话题的真实想法（简短一句，符合你的人设和生活），像朋友随口分享；"
            "如果不自然就直接正常接话，不要强行使用。"
        )

    async def _post_emotion(
        self,
        event: BotEvent,
        character: Any | None,
        user_text: str,
        bot_text: str,
        *,
        inner_thought: str = "",
    ) -> None:
        try:
            snapshot = {
                "style_settings": self.characters.get_style_settings(character),
                "life_schedule": list(character.life_schedule or []) if character else [],
            }
            async with session_scope() as session:
                await EmotionService(session).update_after_exchange(
                    event.bot_id,
                    user_id=event.user_id,
                    group_id=event.group_id,
                    scene=event.scene.value,
                    character_snapshot=snapshot,
                    user_text=user_text,
                    bot_text=bot_text,
                    inner_thought=inner_thought,
                )
        except Exception:  # noqa: BLE001
            logger.exception("异步情感演化失败：%s/%s", event.bot_id, event.user_id)

    async def _run_auto_search(self, event: BotEvent, text: str) -> SearchResult | None:
        try:
            return await self.search.search(
                text,
                trigger_mode=SearchTrigger.AUTO.value,
                bot_id=event.bot_id,
                user_id=event.user_id,
            )
        except Exception:  # noqa: BLE001 - 搜索失败按无资料继续对话
            logger.exception("自动联网搜索失败")
            return None

    async def _resolve_character(self, event: BotEvent) -> tuple[Any | None, str]:
        try:
            character = await self.characters.resolve(event.bot_id, event.group_id)
            if character is not None and not self.characters.matches_scope(
                character, event.scene
            ):
                character = None
            system_prompt = self.characters.build_system_prompt(character)
            if event.call_id:
                system_prompt += (
                    "\n\n【实时语音通话】当前正在和对方通话，系统会将你的回复合成为语音。"
                    "按既有人设像朋友打电话一样接话，先回应对方的意思和情绪，多用短句，日常一两句就好，复杂问题按需展开。"
                    "可以顺着语境少量用‘嗯’‘诶’‘好呀’‘对呀’等语气词，不要每句都加、固定开头或堆砌。"
                    "用自然的逗号、问号表达停顿和语气，避免客服套话、书面汇报或逐条播报。"
                    "只输出实际会说出口的话，不写动作或情绪旁白、括号提示、表情符号和 Markdown。"
                    "不要声称只能打字或不能发语音。"
                )
            elif not event.is_group and event.platform != Platform.QQ_BOT:
                system_prompt += (
                    "\n\n【聊天发送方式】日常闲聊按自然意思回复1至3条短消息，"
                    "多条之间用换行分开，每条可以包含紧密相关的一两句。"
                    "一句能说清就只回一条，不必凑数，不要编号或把半句话拆开。"
                )
            # 思维引导（llm.thinking_hint）：让模型先理解意图再回应
            if self.config.get("llm.thinking_hint", True):
                system_prompt += (
                    "\n\n【思维方式】回复前先结合长期记忆与上下文，理解对方"
                    "真正想聊什么、此刻的情绪如何，再以符合你性格的方式自然"
                    "回应；思考只在内部完成，绝不输出推理过程。"
                )
            return character, system_prompt
        except Exception:  # noqa: BLE001 - 人设失败退回空人设，不阻断对话
            logger.exception("人设解析失败")
            return None, ""

    async def _apply_memory_feedback(self, event: BotEvent, text: str) -> None:
        """根据用户对模糊回忆的认可 / 否认，更新记忆置信度与热度。"""
        last = await self.contexts.get_last_recall(event.session_key())
        if not last or last.get("mode") != MemoryMode.FUZZY.value:
            return
        kind = self.memories.detect_feedback(text)
        if not kind:
            return
        ids = [str(item) for item in (last.get("ids") or [])]
        if not ids:
            return
        try:
            if kind == "confirm":
                await self.memories.confirm(ids, bot_id=event.bot_id)
            else:
                await self.memories.reject(ids, bot_id=event.bot_id)
            await self.contexts.clear_last_recall(event.session_key())
        except Exception:  # noqa: BLE001
            logger.exception("记忆反馈处理失败：%s", kind)

    # ------------------------------------------------------------------
    # 异步后处理
    # ------------------------------------------------------------------
    async def _post_context(
        self, event: BotEvent, user_text: str, assistant_text: str, *, char_budget: int | None = None,
    ) -> None:
        try:
            await self.contexts.append_round(
                event.session_key(),
                user_text,
                assistant_text,
                bot_id=event.bot_id,
                scene=event.scene.value,
                user_id=event.user_id,
                group_id=event.group_id,
                char_budget=char_budget,
            )
        except Exception:  # noqa: BLE001
            logger.exception("异步写入上下文失败：%s", event.session_key())

    async def _post_memory(
        self, event: BotEvent, user_text: str, assistant_text: str, *, log_id: str | None = None,
    ) -> None:
        try:
            async with session_scope() as session:
                if log_id:
                    from backend.services.memory_recovery import recover_memories

                    await recover_memories(session, log_id=log_id)
                else:
                    await MemoryService(session).extract_and_store(event, user_text, assistant_text)
        except Exception:  # noqa: BLE001
            logger.exception("异步提取长期记忆失败：%s", event.user_id)

    async def _post_recall_reinforce(self, entry_ids: list[str], bot_id: str) -> None:
        """后台回馈本轮召回命中的记忆热度（失败不影响对话，也不重试）。"""
        try:
            async with session_scope() as session:
                await MemoryService(session).reinforce(entry_ids, bot_id=bot_id)
        except Exception:  # noqa: BLE001
            logger.debug("异步记忆热度回馈失败：%s", bot_id, exc_info=True)

    # ------------------------------------------------------------------
    # 触发 / 开关
    # ------------------------------------------------------------------
    def _is_triggered(self, event: BotEvent, text: str) -> bool:
        if not event.is_group:
            return bool(self.config.get("dispatch.private_enabled", True))

        if event.is_at_me and self.config.get("dispatch.group_at_enabled", True):
            return True

        if self.config.get("dispatch.group_keyword_enabled", True):
            keywords = self.config.get("dispatch.group_keywords", []) or []
            lowered = text.lower()
            if any(str(keyword).lower() in lowered for keyword in keywords):
                return True

        return False

    @staticmethod
    def _strip_wakeup(text: str, keywords: list) -> str:
        stripped = text.strip()
        for keyword in keywords:
            keyword = str(keyword)
            if keyword and stripped.startswith(keyword):
                return stripped[len(keyword):].lstrip("，,：: \u3000")
        return stripped

    def _ai_enabled(self, settings: dict, rule: GroupRule | None) -> bool:
        if settings.get("ai") is False:
            return False
        if rule is not None and not rule.enabled_ai:
            return False
        return True

    @staticmethod
    def _context_enabled(settings: dict, rule: GroupRule | None) -> bool:
        if settings.get("context") is False:
            return False
        if rule is not None and (rule.extra or {}).get("context_enabled") is False:
            return False
        return bool(get_config().get("dispatch.context_enabled", True))

    # ------------------------------------------------------------------
    # 发送辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _reply_payloads(event: BotEvent, payload: MessagePayload) -> list[MessagePayload]:
        if event.call_id or any(segment.type == "voice" for segment in payload.segments):
            images = [segment for segment in payload.segments if segment.type == "image"]
            if images:
                spoken = MessagePayload.from_segments([segment for segment in payload.segments if segment.type != "image"])
                return ([spoken] if not spoken.is_empty else []) + [MessagePayload.from_segments(images)]
        # shortcut: QQ 官方回复需要逐条 msg_seq，支持前保留单条避免重复序号丢消息。
        if event.call_id or event.is_group or event.platform == Platform.QQ_BOT or any(
            segment.type not in {"text", "image", "emoji"} for segment in payload.segments
        ):
            return [payload]
        text = payload.text
        if "```" in text or re.search(r"(?m)^\s*(?:[-*#•]|\d+[.)、])\s", text):
            return [payload]
        parts = [part.strip() for part in text.splitlines() if part.strip()]
        if len(parts) <= 1 and not re.search(r"https?://\S+", text):
            parts = re.split(r"(?<=[。！？!?])\s*(?=[^\s。！？!?…\"'”’])", text.strip())
        if len(parts) <= 1:
            return [payload]
        parts = parts[:2] + ["\n".join(parts[2:])] if len(parts) > 3 else parts
        bubbles = [MessagePayload.from_text(part) for part in parts]
        bubbles[-1].segments.extend(segment for segment in payload.segments if segment.type != "text")
        return bubbles

    def _can_send_voice(
        self, event: BotEvent, rule: GroupRule | None, *, voice_enabled: bool = True,
        reply_text: str | None = None, history: list[dict] | None = None,
    ) -> bool:
        return self._voice_available(event, rule, voice_enabled=voice_enabled) and self.tts.should_speak(
            event, rule, reply_text=reply_text, history=history,
        )

    def _voice_available(
        self, event: BotEvent, rule: GroupRule | None, *, voice_enabled: bool = True,
    ) -> bool:
        return (
            voice_enabled
            and not event.call_id
            and event.platform not in {Platform.QQ_BOT, Platform.WECHAT_CLAWBOT}
            and bool(self.config.get("tts.enabled", True))
            and self.config.get("tts.trigger", "auto") != "never"
            and (rule is None or rule.enabled_voice)
            and self.tts.available
        )

    async def _build_payload(
        self,
        event: BotEvent,
        rule: GroupRule | None,
        *,
        text: str,
        emoji_segments: list[MessageSegment],
        voice_enabled: bool = True,
        history: list[dict] | None = None,
    ) -> MessagePayload:
        payload = MessagePayload()
        if (len(text) <= min(int(self.config.get("tts.max_chars", 200)), 1000)
                and self._can_send_voice(event, rule, voice_enabled=voice_enabled, reply_text=text, history=history)):
            voice_text = text
            voice_path = await self.tts.synthesize(voice_text)
            if voice_path:
                voice = MessageSegment.voice(voice_path)
                voice.content = voice_text
                payload.add(voice)
                payload.segments.extend(emoji_segments)
                return payload
        if text:
            payload.add_text(text)
        payload.segments.extend(emoji_segments)
        return payload

    async def _send_text(self, event: BotEvent, adapter: BaseAdapter, text: str) -> None:
        try:
            result = await adapter.reply(event, MessagePayload.from_text(text))
            if result.success:
                await self.logs.add_message(
                    bot_id=event.bot_id,
                    platform=event.platform.value,
                    scene=event.scene.value,
                    group_id=event.group_id,
                    user_id=event.user_id,
                    nickname="机器人",
                    direction="out",
                    content=text,
                    segments=[{"type": "text", "content": text}],
                    status="ok",
                )
            else:
                logger.warning("文本发送失败：%s", result.error)
        except AdapterError as exc:
            logger.warning("文本发送异常：%s", exc)

    async def _log_inbound(
        self, event: BotEvent, text: str, *, status: str = "ok", error: str | None = None
    ) -> str:
        log = await self.logs.add_message(
            bot_id=event.bot_id,
            platform=event.platform.value,
            scene=event.scene.value,
            group_id=event.group_id,
            user_id=event.user_id,
            nickname=event.sender.card or event.sender.nickname,
            direction="in",
            content=text,
            segments=[segment.to_dict() for segment in event.segments],
            status=status,
            error=error,
        )
        return log.id

    async def _log_outbound(
        self,
        event: BotEvent,
        payload: MessagePayload,
        *,
        status: str = "ok",
        error: str | None = None,
    ) -> None:
        await self.logs.add_message(
            bot_id=event.bot_id,
            platform=event.platform.value,
            scene=event.scene.value,
            group_id=event.group_id,
            user_id=event.user_id,
            nickname="机器人",
            direction="out",
            content=truncate(payload.text or "\n".join(
                segment.content or "" for segment in payload.segments if segment.type == "voice"
            ), 2000),
            segments=[segment.to_dict() for segment in payload.segments],
            status=status,
            error=error,
        )

    # ------------------------------------------------------------------
    # 通知事件
    # ------------------------------------------------------------------
    async def _handle_notice(self, event: BotEvent) -> None:
        if not event.is_group or not event.group_id:
            return
        account = await self.accounts.get(event.bot_id)
        if account is None:
            return
        adapter = self._resolve_adapter(account)
        rule = await self.groups.get_rule(event.bot_id, str(event.group_id))
        sent_text = await self.groups.handle_notice(event, adapter, rule)
        if sent_text:
            await self.logs.add_message(
                bot_id=event.bot_id,
                platform=event.platform.value,
                scene=event.scene.value,
                group_id=event.group_id,
                user_id=event.user_id,
                nickname="机器人",
                direction="out",
                content=sent_text,
                status="ok",
            )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _resolve_adapter(self, account: Any) -> BaseAdapter:
        if self.adapter is not None:
            return self.adapter
        adapter = self.factory.get(account.id)
        if adapter is not None:
            return adapter
        # 复用账号服务的适配器构造逻辑（含默认地址 / app_id 装配）
        from backend.services.account_service import AccountService

        return AccountService(
            self.session, state_manager=self.state, factory=self.factory
        ).build_adapter(account)

    @staticmethod
    def _last_user_message(messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            if message.get("role") == "user":
                content = message.get("content") or ""
                if isinstance(content, list):
                    return "\n".join(str(part.get("text") or "") for part in content
                                     if isinstance(part, dict) and part.get("type") == "text")
                return str(content)
        return ""
