"""LLM 模型对接（开发文档 4.7）：兼容 OpenAI 格式接口，三级模型覆盖。

推理模型支持：DeepSeek Reasoner 的 ``reasoning_content`` 字段与
``<think>`` 思考标签会被剥离出正式回复（``LLMReply.reasoning``），
思考过程只进 AI 日志，不会发给用户。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from backend.common.exceptions import LLMError, NotFoundError, ValidationError
from backend.common.logger import get_logger
from backend.common.utils import estimate_message_tokens, estimate_text_tokens, truncate
from backend.core.config_loader import get_config
from backend.database.models import LlmModel
from backend.repositories.account_repo import AccountRepo
from backend.repositories.group_rule_repo import GroupRuleRepo
from backend.repositories.model_repo import ModelRepo

logger = get_logger("yuexu.service.llm")

# 推理模型思考标签：闭合的整体剥离；未闭合的（流式中断）截掉其后全部
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def strip_thinking(text: str) -> tuple[str, str]:
    """剥离思考过程，返回 (正式回复, 思考内容)。"""
    if not text:
        return "", ""
    thoughts: list[str] = []

    def _collect(match: re.Match) -> str:
        thoughts.append(match.group(0)[7:-8].strip())
        return ""

    cleaned = _THINK_BLOCK.sub(_collect, text)
    if "<think>" in cleaned.lower():
        head, _, tail = cleaned.partition("<think>")
        cleaned, thought = head, tail.split("</think>")[0]
        if thought.strip():
            thoughts.append(thought.strip())
    return cleaned.strip(), "\n".join(thought for thought in thoughts if thought)

# 进程级连接池：按服务 origin 复用 AsyncClient，避免每次请求重建 TCP/TLS。
# 缓存同时记录构造器身份：测试通过替换 ``httpx.AsyncClient`` 注入
# MockTransport 时自动绕过池化，保证每个用例拿到自己的 mock 客户端。
_CLIENTS: dict[str, tuple[Any, httpx.AsyncClient]] = {}
_CLIENT_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)


def _shared_client(url: str) -> httpx.AsyncClient:
    parsed = httpx.URL(url)
    origin = f"{parsed.scheme}://{parsed.host}" + (
        f":{parsed.port}" if parsed.port not in (80, 443, None) else ""
    )
    constructor = httpx.AsyncClient
    entry = _CLIENTS.get(origin)
    if entry is not None and entry[0] is constructor and not entry[1].is_closed:
        return entry[1]
    client = constructor(timeout=None, limits=_CLIENT_LIMITS)
    if entry is not None and not entry[1].is_closed:
        try:
            asyncio.get_running_loop().create_task(entry[1].aclose())
        except Exception:  # noqa: BLE001
            pass
    _CLIENTS[origin] = (constructor, client)
    return client


async def close_llm_clients() -> None:
    """应用关停时统一释放连接池。"""
    entries = list(_CLIENTS.values())
    _CLIENTS.clear()
    for _constructor, client in entries:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001
            pass


@dataclass
class LLMReply:
    """模型调用结果。"""

    success: bool
    content: str
    model_id: str | None = None
    model_name: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    error: str | None = None
    # 推理模型的思考过程（已从 content 剥离，只进日志不发给用户）
    reasoning: str = ""
    # 模型发起的工具调用请求（OpenAI 格式，Agent 循环使用；普通对话为空）
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # 超时 / 网络错误 / 5xx：可重试（或切换备用模型）；4xx 配置类错误不可重试
    retryable: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


class LLMService:
    """OpenAI 兼容接口客户端。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ModelRepo(session)
        self.config = get_config()

    # ------------------------------------------------------------------
    # 模型解析
    # ------------------------------------------------------------------
    async def resolve_model(
        self, bot_id: str | None = None, group_id: str | None = None
    ) -> LlmModel | None:
        """三级覆盖：单群模型 > 账号模型 > 全局默认模型。"""
        if bot_id and group_id:
            rule = await GroupRuleRepo(self.session).get_rule(bot_id, group_id)
            if rule and rule.model_id:
                model = await self.repo.get(rule.model_id)
                if model and model.enabled:
                    return model

        if bot_id:
            account = await AccountRepo(self.session).get(bot_id)
            if account and account.model_id:
                model = await self.repo.get(account.model_id)
                if model and model.enabled:
                    return model

        default_model_id = self.config.get("llm.default_model_id")
        if default_model_id:
            model = await self.repo.get(str(default_model_id))
            if model and model.enabled:
                return model

        return await self.repo.get_default()

    async def get_model(self, model_id: str) -> LlmModel:
        model = await self.repo.get(model_id)
        if not model:
            raise NotFoundError("模型配置不存在")
        return model

    async def list_models(self) -> list[LlmModel]:
        return await self.repo.list(limit=200, order_by="created_at", desc=True)

    async def create_model(self, data: dict[str, Any]) -> LlmModel:
        data = self._prepare_model_data(data)
        if not data.get("name"):
            data["name"] = data.get("model_name") or "未命名模型"
        if data.get("is_default"):
            await self.repo.clear_default()
        return await self.repo.create(**data)

    async def update_model(self, model_id: str, data: dict[str, Any]) -> LlmModel:
        model = await self.get_model(model_id)
        headers_provided = "headers" in (data.get("extra") or {})
        data = self._prepare_model_data(data, model)
        if "base_url" in data:
            new_base = self._discovery_base(data["base_url"])
            try:
                same_endpoint = self._discovery_base(model.base_url) == new_base
            except ValidationError:
                same_endpoint = False
            if not same_endpoint:
                data.setdefault("api_key", "")
                if not headers_provided:
                    data["extra"].pop("headers", None)
        if data.get("is_default"):
            await self.repo.clear_default(except_id=model_id)
        return await self.repo.update(model, **data)

    @staticmethod
    def _prepare_model_data(data: dict[str, Any], model: LlmModel | None = None) -> dict[str, Any]:
        data = dict(data)
        extra = dict(data.get("extra", model.extra if model else {}) or {})
        for key in ("context_window", "max_output_tokens"):
            if key in data:
                value = data.pop(key)
                if value is None:
                    extra.pop(key, None)
                else:
                    extra[key] = value
            value = extra.get(key)
            if value is not None and (type(value) is not int or value <= 0):
                raise ValidationError(f"{key} 必须为正整数")
        max_tokens = data.get("max_tokens", model.max_tokens if model else 1024)
        if type(max_tokens) is not int or max_tokens <= 0:
            raise ValidationError("回复 Token 上限必须为正整数")
        for key, label in (("context_window", "上下文窗口"), ("max_output_tokens", "模型输出上限")):
            if extra.get(key) and max_tokens > extra[key]:
                raise ValidationError(f"回复 Token 上限不能超过{label}（{extra[key]}）")
        data["extra"] = extra
        return data

    async def discover_models(
        self, *, base_url: str, api_key: str | None = None, model_id: str | None = None,
        provider: str | None = None, model_name: str | None = None,
    ) -> dict[str, Any]:
        """只读取供应商返回的容量信息，未知容量保留为空。"""
        base = self._discovery_base(base_url)
        saved = await self.get_model(model_id) if model_id else None
        try:
            same_endpoint = saved is not None and self._discovery_base(saved.base_url) == base
        except ValidationError:
            same_endpoint = False
        api_key = (api_key or "").strip()
        if "***" in api_key:
            api_key = ""
        if not api_key and same_endpoint:
            api_key = saved.api_key or ""
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if same_endpoint and isinstance((saved.extra or {}).get("headers"), dict):
            headers.update({str(key): str(value) for key, value in saved.extra["headers"].items()})
        warning = ""
        try:
            client = _shared_client(f"{base}/models")
            response = await client.get(f"{base}/models", headers=headers, timeout=15)
            if response.status_code >= 300:
                hints = {
                    401: "鉴权失败，请检查 API Key", 403: "没有访问权限，请检查 API Key",
                    404: "不支持模型发现接口，请手动填写模型与容量",
                }
                raise LLMError(f"获取模型失败（HTTP {response.status_code}）：{hints.get(response.status_code, '请检查服务地址或稍后重试')}")
            payload = response.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise LLMError("模型列表格式不符合 OpenAI 兼容接口，请手动填写")
            models: dict[str, dict[str, Any]] = {}
            for item in payload["data"]:
                if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"].strip():
                    models[item["id"]] = {"id": item["id"], **self._remote_limits(item)}
            if (provider or (saved.provider if saved else "")) == "ollama" and model_name in models:
                ollama_base = base.removesuffix("/v1")
                try:
                    detail_response = await client.post(
                        f"{ollama_base}/api/show", json={"model": model_name}, headers=headers,
                        timeout=15,
                    )
                    detail_response.raise_for_status()
                    detail = detail_response.json()
                    if not isinstance(detail, dict):
                        raise TypeError("invalid model detail")
                    limits = self._remote_limits(detail)
                    info = detail.get("model_info") or {}
                    if isinstance(info, dict):
                        for key, value in info.items():
                            if key.endswith(".context_length") and type(value) is int and value > 0:
                                limits["context_window"] = value
                                break
                    models[model_name].update({key: value for key, value in limits.items() if value is not None})
                except (httpx.HTTPError, ValueError, TypeError):
                    warning = "已获取模型列表，但无法获取所选 Ollama 模型详情，请手动确认容量。"
        except httpx.TimeoutException:
            raise LLMError("获取模型超时，请检查服务地址或稍后重试") from None
        except httpx.HTTPError:
            raise LLMError("无法连接模型服务，请检查服务地址与网络") from None
        except ValueError:
            raise LLMError("模型服务未返回有效 JSON，请检查服务地址") from None
        result: dict[str, Any] = {"models": list(models.values())}
        if not models:
            warning = "服务未返回可用模型，请手动填写模型与容量。"
        elif any(item["context_window"] is None or item["max_output_tokens"] is None for item in models.values()):
            warning = warning or "部分模型未提供上下文或输出上限，未知容量请查阅供应商文档后手动填写。"
        if warning:
            result["warning"] = warning
        return result

    @classmethod
    def _discovery_base(cls, base_url: str) -> str:
        try:
            parsed = httpx.URL(base_url.strip())
            if parsed.scheme not in {"http", "https"} or not parsed.host or parsed.userinfo or parsed.query or parsed.fragment:
                raise ValueError("invalid base URL")
            return str(httpx.URL(cls._chat_url(str(parsed)))).removesuffix("/chat/completions")
        except (httpx.InvalidURL, ValueError):
            raise ValidationError("API 地址须为 HTTP(S) 地址，不能包含账号、查询参数或片段") from None

    @staticmethod
    def _remote_limits(data: dict[str, Any]) -> dict[str, int | None]:
        result: dict[str, int | None] = {}
        top_provider = data.get("top_provider")
        sources = [data, top_provider] if isinstance(top_provider, dict) else [data]
        for key, aliases in (
            ("context_window", ("context_window", "context_length", "max_context_tokens", "max_model_len")),
            ("max_output_tokens", ("max_output_tokens", "max_completion_tokens")),
        ):
            result[key] = next((source[name] for source in sources for name in aliases
                                if type(source.get(name)) is int and source[name] > 0), None)
        return result

    async def delete_model(self, model_id: str) -> None:
        model = await self.get_model(model_id)
        if model.is_default:
            raise ValidationError("默认模型不能直接删除，请先切换默认模型")
        await self.repo.delete(model)

    async def set_default(self, model_id: str) -> LlmModel:
        model = await self.get_model(model_id)
        await self.repo.clear_default(except_id=model_id)
        model.is_default = True
        model.enabled = True
        await self.session.flush()
        return model

    # ------------------------------------------------------------------
    # 调用
    # ------------------------------------------------------------------
    def input_char_budget(
        self, model: LlmModel | None, *, char_cap: int | None = None,
    ) -> int:
        """模型窗口扣除输出与消息开销后的字符预算。

        旧实现按「4 个字符 ≈ 1 token」把 token 折算成字符，对中文场景等于把
        可用上下文压到三分之一：8k 窗口只剩约 1.7k 字历史，长对话很快被摘要
        顶掉。这里改用 ``estimate_text_tokens`` 同一套口径——汉字约 1 token、
        其他字符约 0.3 token——字符预算取「最坏情况全中文」，再留 10% 余量。
        显式配置的 ``llm.context_char_budget`` 仍然优先（限制费用 / 保持旧行为）。
        """
        cap = int(self.config.get("llm.context_char_budget", 0) if char_cap is None else char_cap)
        window = (model.extra or {}).get("context_window") if model else None
        if type(window) is not int or window <= 0:
            return cap if cap > 0 else 6000
        # 预留输出上限与固定开销（系统消息、角色标记、工具定义）
        available = max(1, window - int(model.max_tokens or 1024) - 256)
        # 每 1 token 按 1 个汉字估（中文最坏情况），再留 10% 安全余量：
        # 低估会触发服务商 400 错误，高估则浪费窗口，这里取偏保守的一侧。
        budget = max(1, int(available * 0.9))
        return min(cap, budget) if cap > 0 else budget

    @staticmethod
    def _fit_messages(
        messages: list[dict[str, Any]], window: int, output_tokens: int,
        tools: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]] | None:
        """每个实际请求独立校验窗口，备用模型更小时仅移除最旧完整轮次。

        窗口校验用 ``estimate_message_tokens``（汉字 1 token、其他字符 0.3
        token）代替旧的 UTF-8 字节数：字节数对中文高估约 3 倍，会把本来放得
        下的历史轮次误判为超限。工具定义仍按 JSON 字节数折算，保持保守。
        """
        def cost(message):
            size = estimate_message_tokens(message.get("content"))
            tool_calls = message.get("tool_calls") or []
            if tool_calls:
                size += estimate_text_tokens(
                    json.dumps(tool_calls, ensure_ascii=False)
                )
            return size

        available = window - output_tokens - 256
        if tools:
            available -= len(json.dumps(tools, ensure_ascii=False).encode("utf-8"))
        system_indices = {index for index, item in enumerate(messages) if item.get("role") == "system"}
        available -= sum(cost(messages[index]) for index in system_indices)
        rounds: list[list[int]] = []
        for index, item in enumerate(messages):
            if index in system_indices:
                continue
            if item.get("role") == "user" or not rounds:
                rounds.append([])
            rounds[-1].append(index)
        selected = set(system_indices)
        for round_indices in reversed(rounds):
            size = sum(cost(messages[index]) for index in round_indices)
            if size > available:
                if round_indices is rounds[-1]:
                    return None
                break
            selected.update(round_indices)
            available -= size
        if available < 0:
            return None
        return [item for index, item in enumerate(messages) if index in selected]

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: LlmModel | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMReply:
        """调用模型；失败不抛异常，返回 success=False 的降级结果。

        ``tools`` / ``tool_choice`` 为 OpenAI Function Calling 格式；模型决定
        调用工具时结果放在 ``LLMReply.tool_calls``（此时 content 可能为空）。
        """
        if model is None:
            model = await self.resolve_model()
        if model is None:
            return LLMReply(
                success=False,
                content="",
                error="尚未配置任何 LLM 模型，请先在后台「模型配置」中添加",
            )
        if not model.api_key and model.provider != "ollama":
            return LLMReply(
                success=False,
                content="",
                model_id=model.id,
                model_name=model.model_name,
                error="模型未配置 API Key",
            )

        url = self._chat_url(model.base_url)
        payload: dict[str, Any] = {
            "model": model.model_name,
            "messages": messages,
            "temperature": model.temperature if temperature is None else temperature,
            "top_p": model.top_p,
            "max_tokens": model.max_tokens if max_tokens is None else max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"
        extra = model.extra or {}
        if isinstance(extra.get("body"), dict):
            payload.update(extra["body"])
        output_limit = payload.get("max_completion_tokens", payload.get("max_tokens"))
        if type(output_limit) is not int or output_limit <= 0:
            return LLMReply(
                success=False, content="", model_id=model.id, model_name=model.model_name,
                error="模型输出上限必须是正整数",
            )
        window = extra.get("context_window")
        if type(window) is int and window > 0:
            fitted = self._fit_messages(
                payload["messages"], window, output_limit, payload.get("tools"),
            )
            if fitted is None:
                return LLMReply(
                    success=False, content="", model_id=model.id, model_name=model.model_name,
                    error="当前输入和系统提示超过模型上下文窗口，请缩短本条消息或使用更大窗口的模型",
                )
            payload["messages"] = fitted
        headers = {"Content-Type": "application/json"}
        if model.api_key:
            headers["Authorization"] = f"Bearer {model.api_key}"
        if isinstance(extra.get("headers"), dict):
            headers.update({str(k): str(v) for k, v in extra["headers"].items()})

        timeout = float(model.timeout or self.config.get("llm.timeout", 60))
        started = time.perf_counter()
        try:
            client = _shared_client(url)
            response = await client.post(url, json=payload, headers=headers, timeout=timeout)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                snippet = truncate(response.text, 300)
                return LLMReply(
                    success=False,
                    content="",
                    model_id=model.id,
                    model_name=model.model_name,
                    latency_ms=latency_ms,
                    retryable=response.status_code >= 500,
                    error=f"模型接口返回 {response.status_code}：{snippet}",
                )
            data = response.json()
            content, reasoning, tool_calls = self._extract_reply(data)
            usage = data.get("usage") or {}
            if not content and not tool_calls:
                return LLMReply(
                    success=False,
                    content="",
                    model_id=model.id,
                    model_name=model.model_name,
                    latency_ms=latency_ms,
                    reasoning=reasoning,
                    error="模型返回内容为空",
                    raw=data,
                )
            if reasoning:
                logger.debug(
                    "推理模型思考完成（%s 字），已剥离出正式回复", len(reasoning)
                )
            logger.debug("LLM 调用成功（%s，%sms）", model.model_name, latency_ms)
            return LLMReply(
                success=True,
                content=content,
                model_id=model.id,
                model_name=data.get("model") or model.model_name,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                latency_ms=latency_ms,
                reasoning=reasoning,
                tool_calls=tool_calls,
                raw=data,
            )
        except httpx.TimeoutException:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.warning("LLM 调用超时：%s", model.model_name)
            return LLMReply(
                success=False, content="", model_id=model.id,
                model_name=model.model_name, latency_ms=latency_ms,
                retryable=True,
                error=f"模型调用超时（{timeout}s）",
            )
        except httpx.HTTPError as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.warning("LLM 调用失败：%s", exc)
            return LLMReply(
                success=False, content="", model_id=model.id,
                model_name=model.model_name, latency_ms=latency_ms,
                retryable=True,
                error=f"网络请求失败：{exc}",
            )
        except (ValueError, KeyError) as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            logger.warning("LLM 响应解析失败：%s", exc)
            return LLMReply(
                success=False, content="", model_id=model.id,
                model_name=model.model_name, latency_ms=latency_ms,
                error=f"响应解析失败：{exc}",
            )

    async def _fallback_model(self) -> LlmModel | None:
        """备用模型（llm.fallback_model_id 配置，未配置 / 已停用时跳过）。"""
        model_id = self.config.get("llm.fallback_model_id")
        if not model_id:
            return None
        try:
            model = await self.repo.get(str(model_id))
        except Exception:  # noqa: BLE001
            return None
        return model if model and model.enabled else None

    async def chat_with_fallback(
        self,
        messages: list[dict[str, Any]],
        *,
        bot_id: str | None = None,
        group_id: str | None = None,
        model: LlmModel | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMReply:
        """三级降级：可重试错误重试一次 → 备用模型 → 兜底话术。

        超时单独处理：一次超时已经把整个 ``timeout``（默认 60s）耗完，用同一
        个模型再试一次通常是「再等一个 60s」，用户侧表现为机器人长时间不回。
        因此当**配置了备用模型**时，超时直接切备用模型，不再重试主模型；
        没有备用模型时保持原有的一次重试，避免单次网络抖动变成兜底话术。
        """
        if model is None:
            model = await self.resolve_model(bot_id, group_id)
        tool_options = {"tools": tools, "tool_choice": tool_choice} if tools else {}
        reply = await self.chat(messages, model=model, **tool_options)
        fallback_model: LlmModel | None = None
        if not reply.success:
            fallback_model = await self._fallback_model()
        # 超时且配置了另一个备用模型 → 跳过主模型重试，直接进入备用模型分支
        skip_same_retry = bool(
            not reply.success
            and reply.retryable
            and "超时" in str(reply.error or "")
            and fallback_model is not None
            and fallback_model.id != reply.model_id
        )
        if skip_same_retry:
            logger.warning("LLM 主模型超时，直接切换备用模型：%s", fallback_model.model_name)
        elif not reply.success and reply.retryable:
            logger.warning("LLM 首次调用失败（%s），0.5s 后重试一次", reply.error)
            await asyncio.sleep(0.5)
            reply = await self.chat(messages, model=model, **tool_options)
        if not reply.success:
            if fallback_model is None:
                fallback_model = await self._fallback_model()
            if fallback_model is not None and fallback_model.id != reply.model_id:
                logger.warning(
                    "LLM 主模型不可用，切换备用模型：%s", fallback_model.model_name
                )
                retry = await self.chat(messages, model=fallback_model, **tool_options)
                if retry.success:
                    return retry
        if reply.success:
            return reply
        logger.error("LLM 降级：%s", reply.error)
        fallback = str(
            self.config.get("dispatch.fallback_reply", "……刚刚走神了一下，你再发一次好不好？")
        )
        reply.content = fallback
        return reply

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    @staticmethod
    def _chat_url(base_url: str) -> str:
        base = (base_url or "").rstrip("/")
        if not base:
            base = "https://api.deepseek.com"
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    @staticmethod
    def _extract_reply(data: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]]]:
        """提取 (正式回复, 思考过程, 工具调用请求)：兼容 reasoning_content 与 <think>。"""
        choices = data.get("choices") or []
        if not choices:
            return "", "", []
        message = choices[0].get("message") or {}
        reasoning = str(message.get("reasoning_content") or "").strip()
        content = message.get("content")
        if isinstance(content, list):
            # 兼容部分接口的多段 content
            content = "".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict)
            ).strip()
        cleaned, tag_reasoning = strip_thinking(str(content or ""))
        if tag_reasoning:
            reasoning = f"{reasoning}\n{tag_reasoning}".strip()
        tool_calls: list[dict[str, Any]] = []
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            function = call.get("function") or {}
            tool_calls.append({
                "id": str(call.get("id") or ""),
                "type": str(call.get("type") or "function"),
                "function": {
                    "name": str(function.get("name") or ""),
                    "arguments": str(function.get("arguments") or "{}"),
                },
            })
        return cleaned, reasoning, tool_calls

    async def test_model(self, model_id: str) -> LLMReply:
        """后台连通性测试。"""
        model = await self.get_model(model_id)
        return await self.chat(
            [{"role": "user", "content": "你好，请只回复两个字：在的"}],
            model=model,
            max_tokens=min(32, model.max_tokens),
        )

    async def ensure_model(self, model_id: str) -> LlmModel:
        model = await self.repo.get(model_id)
        if not model:
            raise LLMError("模型配置不存在")
        return model
