"""中文语义向量化抽象：builtin / onnx / api 三种实现，统一供向量库预计算向量。

设计要点（对应检索能力升级）：
- 向量库写入与查询统一由 provider 预计算向量后显式传给 Chroma，
  彻底替换 Chroma 默认的英文 MiniLM 模型（对中文语义检索无效）；
- ``signature`` 唯一标识一个向量空间：provider / 模型 / 维度任一变化即变化，
  启动时与向量库记录的签名比对，不一致自动重建索引，防止新旧向量混用；
- ``builtin``：零依赖中文字符级特征哈希向量，开箱即用（默认）；
- ``onnx``：本地 ONNX 中文模型（bge-small-zh 类，CLS 池化 + 归一化）；
- ``api``：OpenAI 兼容 /embeddings 接口，批量请求 + 结果 LRU 缓存。
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from abc import ABC, abstractmethod
from collections import OrderedDict
from pathlib import Path
from typing import Any

from backend.common.logger import get_logger
from backend.common.utils import extract_keywords

logger = get_logger("yuexu.embedding")

EMBEDDING_SIGNATURE_KEY = "yuexu:embedding_sig"

_WHITESPACE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE.sub("", (text or "").lower())


def _token_hash(token: str, dim: int) -> tuple[int, int]:
    """特征哈希：token 映射到 [0, dim) 桶并附带符号位，降低碰撞偏置。"""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, 1 if (value >> 63) & 1 else -1


class EmbeddingProvider(ABC):
    """向量化 provider 抽象：同文本必须产生同向量（确定性）。

    ``calibration_scale``：不同算法的余弦分数尺度差异很大（字符级算法的
    复述对约 0.15~0.3，神经嵌入约 0.6~0.9），乘以校准系数把分数统一到
    神经嵌入的量纲，使精准/模糊阈值与查重阈值对所有 provider 通用。
    """

    name: str = "base"
    calibration_scale: float = 1.0

    def calibrate(self, cosine: float) -> float:
        return max(0.0, min(1.0, cosine * self.calibration_scale))

    @property
    @abstractmethod
    def signature(self) -> str:
        """向量空间签名（provider + 模型 + 维度），变化即需重建索引。"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化，返回与输入等长的 L2 归一化向量列表。"""


def _provider_section(config) -> dict[str, Any]:  # noqa: ANN001
    """读取 memory.embedding 段，配置对象不标准时按空段处理。"""
    section = getattr(config, "section", None)
    if section is None:
        return {}
    try:
        return config.section("memory.embedding") or {}
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------------------
# builtin：零依赖中文字符级特征哈希（默认）
# ---------------------------------------------------------------------------
# 常用高频字降权表：的/是/我等字几乎出现在所有中文句子中，区分度极低
_COMMON_CHARS = set(
    "的一是不了在人有我他这个们中来上大为和国地到以说时要就出会可也你对生能而子那得于着下自之年过发后作里用道行所然家种事成方多经么去法学如都同现当没动面起看定天分还进好小部其些主样理心她本前开但因只从想实日军者意无力它与长把机十民第公此已工使情明性知全三又关点正业外将两高间由问很最重并物手应战向头文体政美相见被利什二吗呢吧啊呀哦嘛啦恩嘛"
)

# 疑问 / 口语填充词：只增加查询噪声，不参与匹配（双侧对称移除，安全）
_FILLER_TOKENS = (
    "什么", "来着", "一下", "请问", "告诉我", "想想", "是不是", "有没有",
    "来说", "来说说", "呢吧", "啥来", "什", "么",
)


def _token_weights(text: str) -> dict[str, float]:
    """token → 权重：高频单字 0.6、普通单字 1.5、二元组 1.0、关键词 1.0。

    疑问填充词（什么/来着/请问…）移除后再返回，查询侧不再被口语噪声稀释。

    重复 token 按子线性 TF 饱和（BM25 风格）：累计出现 k 次的 token 权重
    乘以 ``(1+ln k)/k``。单次出现权重不变（短查询完全向后兼容）；重复
    出现仍有增益但被压缩——「火锅火锅火锅」式的长记忆不能再靠重复把
    余弦分数线性刷高，词形分布的相对结构保留得更真实。
    """
    normalized = _normalize(text)
    raw: dict[str, float] = {}
    counts: dict[str, int] = {}
    for index, char in enumerate(normalized):
        raw[char] = raw.get(char, 0.0) + (0.6 if char in _COMMON_CHARS else 1.5)
        counts[char] = counts.get(char, 0) + 1
        if index + 1 < len(normalized):
            bigram = normalized[index : index + 2]
            raw[bigram] = raw.get(bigram, 0.0) + 1.0
            counts[bigram] = counts.get(bigram, 0) + 1
    for keyword in extract_keywords(text, limit=6):
        token = _normalize(keyword)
        if token:
            raw[token] = raw.get(token, 0.0) + 1.0
            counts[token] = counts.get(token, 0) + 1
    for filler in _FILLER_TOKENS:
        raw.pop(filler, None)
    weights: dict[str, float] = {}
    for token, weight in raw.items():
        count = counts.get(token, 1)
        weights[token] = (
            weight if count <= 1 else weight * (1.0 + math.log(count)) / count
        )
    return weights


def sparse_cosine(first: dict[str, float], second: dict[str, float]) -> float:
    """精确稀疏余弦：直接对 token 权重求交，无特征哈希碰撞噪声。"""
    if not first or not second:
        return 0.0
    if len(first) > len(second):
        first, second = second, first
    dot = sum(weight * second.get(token, 0.0) for token, weight in first.items())
    if dot <= 0.0:
        return 0.0
    norm_first = math.sqrt(sum(w * w for w in first.values()))
    norm_second = math.sqrt(sum(w * w for w in second.values()))
    return dot / (norm_first * norm_second)


class BuiltinEmbedding(EmbeddingProvider):
    """中文字符级 TF 向量：单字（按字频加权）+ 二元组 + 关键词，L2 归一化。

    语义能力介于关键词匹配与神经模型之间，胜在零依赖、零下载、确定性；
    稀疏路径（``sparse_embed``）供内置向量存储做精确余弦检索，无哈希噪声。
    """

    name = "builtin"
    # TF-IDF 加权后的实测分布：无关对（无共享 token）得 0 分、弱词法相关
    # ~0.35、词法复述 ≥0.55、近重复 ≥0.85；×7 校准后：无关 ≤0.3（个别
    # 弱重叠边界 ~0.6 归模糊线索）、弱相关 ≥0.5（模糊可见）、复述 ≥0.9
    # （精准召回）、近重复 1.0（查重），与神经嵌入的常规阈值对齐
    calibration_scale = 7.0

    def __init__(self, dim: int = 512) -> None:
        self.dim = max(64, int(dim))
        self._sig = f"builtin|{self.dim}"

    @property
    def signature(self) -> str:
        return self._sig

    def sparse_embed(self, text: str) -> dict[str, float]:
        return _token_weights(text)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        weights = _token_weights(text)
        vector = [0.0] * self.dim
        for token, weight in weights.items():
            bucket, sign = _token_hash(token, self.dim)
            vector[bucket] += weight * sign
        norm = math.sqrt(sum(value * value for value in vector))
        if norm <= 0.0:
            return vector
        return [value / norm for value in vector]


# ---------------------------------------------------------------------------
# onnx：本地 ONNX 中文模型（bge-small-zh 类）
# ---------------------------------------------------------------------------
class OnnxZhEmbedding(EmbeddingProvider):
    """本地 ONNX 中文 embedding 模型：WordPiece 分词 + CLS 池化 + 归一化。

    模型目录需包含 ``model.onnx`` 与 ``vocab.txt``（bge-small-zh-v1.5 等
    BERT 结构模型导出）。依赖 ``onnxruntime``，缺失或模型不可用时由工厂
    降级为 builtin 并记录错误日志。
    """

    name = "onnx"
    _MAX_TOKENS = 512

    def __init__(self, model_path: str | Path) -> None:
        import onnxruntime as ort  # noqa: PLC0415 - 缺依赖时由工厂降级

        directory = Path(model_path)
        model_file = directory / "model.onnx"
        vocab_file = directory / "vocab.txt"
        if not model_file.is_file() or not vocab_file.is_file():
            raise FileNotFoundError(
                f"ONNX 模型目录不完整（需要 model.onnx 与 vocab.txt）：{directory}"
            )
        self._vocab = self._load_vocab(vocab_file)
        options = ort.SessionOptions()
        options.intra_op_num_threads = max(1, min(4, self._cpu_count()))
        self._session = ort.InferenceSession(
            str(model_file), sess_options=options, providers=["CPUExecutionProvider"]
        )
        input_shape = self._session.get_inputs()[0].shape
        hidden_shape = self._session.get_outputs()[0].shape
        self.dim = int(hidden_shape[-1]) if hidden_shape and isinstance(hidden_shape[-1], int) else 512
        self._input_names = [item.name for item in self._session.get_inputs()]
        self._sig = f"onnx|{directory.name}|{self.dim}|{input_shape}"

    @property
    def signature(self) -> str:
        return self._sig

    @staticmethod
    def _cpu_count() -> int:
        import os

        return os.cpu_count() or 2

    @staticmethod
    def _load_vocab(vocab_file: Path) -> dict[str, int]:
        vocab: dict[str, int] = {}
        with vocab_file.open("r", encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                token = line.rstrip("\n")
                if token:
                    vocab[token] = index
        return vocab

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._embed_sync, texts)

    def _embed_sync(self, texts: list[str]) -> list[list[float]]:
        token_ids = [self._tokenize(text) for text in texts]
        batch = len(token_ids)
        length = min(self._MAX_TOKENS, max((len(ids) for ids in token_ids), default=1)) or 1
        input_ids = [[0] * length for _ in range(batch)]
        attention = [[0] * length for _ in range(batch)]
        for row, ids in enumerate(token_ids):
            ids = ids[: length - 1]
            input_ids[row][: len(ids)] = ids
            attention[row][: len(ids)] = [1] * len(ids)
        feeds: dict[str, Any] = {
            "input_ids": input_ids,
            "attention_mask": attention,
        }
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = [[0] * length for _ in range(batch)]
        output = self._session.run(None, feeds)[0]
        vectors: list[list[float]] = []
        for row in range(batch):
            vector = [float(value) for value in output[row][0]]  # CLS 池化
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append([value / norm for value in vector] if norm > 0 else vector)
        return vectors

    def _tokenize(self, text: str) -> list[int]:
        ids: list[int] = []
        for token in self._basic_tokenize(text):
            for piece in self._wordpiece(token):
                if len(ids) >= self._MAX_TOKENS - 1:
                    return ids + [self._vocab.get("[SEP]", 102)]
                ids.append(piece)
        return [self._vocab.get("[CLS]", 101), *ids, self._vocab.get("[SEP]", 102)]

    def _basic_tokenize(self, text: str) -> list[str]:
        cleaned = _WHITESPACE.sub(" ", (text or "").strip())
        tokens: list[str] = []
        buffer = ""
        for char in cleaned:
            if char.isspace():
                if buffer:
                    tokens.append(buffer.lower())
                    buffer = ""
            elif self._is_cjk(char) or not char.isalnum():
                if buffer:
                    tokens.append(buffer.lower())
                    buffer = ""
                if self._is_cjk(char):
                    tokens.append(char)
            else:
                buffer += char
        if buffer:
            tokens.append(buffer.lower())
        return tokens

    @staticmethod
    def _is_cjk(char: str) -> bool:
        code = ord(char)
        return 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF

    def _wordpiece(self, token: str, max_chars: int = 100) -> list[int]:
        if len(token) > max_chars:
            return [self._vocab.get("[UNK]", 100)]
        pieces: list[int] = []
        start = 0
        unk = self._vocab.get("[UNK]", 100)
        while start < len(token):
            end = len(token)
            matched = unk
            while start < end:
                piece = token[start:end] if start == 0 else f"##{token[start:end]}"
                if piece in self._vocab:
                    matched = self._vocab[piece]
                    break
                end -= 1
            if end <= start:
                return [unk]
            pieces.append(matched)
            start = end
        return pieces


# ---------------------------------------------------------------------------
# api：OpenAI 兼容 /embeddings 接口
# ---------------------------------------------------------------------------
class ApiEmbedding(EmbeddingProvider):
    """OpenAI 兼容 embedding 接口（如硅基流动 bge 系列），批量 + LRU 缓存。"""

    name = "api"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 10.0,
        batch: int = 16,
        cache_size: int = 1024,
    ) -> None:
        if not base_url or not model:
            raise ValueError("api embedding 需要 base_url 与 model 配置")
        self._base_url = base_url.rstrip("/")
        self._api_key = (api_key or "").strip()
        self._model = model
        self._timeout = max(1.0, float(timeout))
        self._batch = max(1, int(batch))
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = max(64, int(cache_size))
        self._client = None
        self._sig = f"api|{self._model}|{self._base_url}"

    @property
    def signature(self) -> str:
        return self._sig

    def _http(self):
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float] | None] = [None] * len(texts)
        pending: list[int] = []
        for index, text in enumerate(texts):
            cached = self._cache_get(text)
            if cached is not None:
                vectors[index] = cached
            else:
                pending.append(index)
        for start in range(0, len(pending), self._batch):
            chunk = pending[start : start + self._batch]
            results = await self._request([texts[index] for index in chunk])
            for index, vector in zip(chunk, results):
                vectors[index] = vector
                self._cache_put(texts[index], vector)
        return [list(vector or []) for vector in vectors]

    async def _request(self, texts: list[str]) -> list[list[float]]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = await self._http().post(
            f"{self._base_url}/embeddings",
            json={"model": self._model, "input": texts},
            headers=headers,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"embedding 接口返回 {response.status_code}：{response.text[:200]}")
        data = response.json().get("data") or []
        by_index = {int(item.get("index") or position): item for position, item in enumerate(data)}
        vectors: list[list[float]] = []
        for position in range(len(texts)):
            item = by_index.get(position)
            if not item or not isinstance(item.get("embedding"), list):
                raise RuntimeError("embedding 接口返回结构异常")
            vectors.append([float(value) for value in item["embedding"]])
        return vectors

    def _cache_get(self, text: str) -> list[float] | None:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        vector = self._cache.get(key)
        if vector is not None:
            self._cache.move_to_end(key)
        return vector

    def _cache_put(self, text: str, vector: list[float]) -> None:
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self._cache[key] = vector
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


# ---------------------------------------------------------------------------
# 工厂（进程级单例）
# ---------------------------------------------------------------------------
_PROVIDER: EmbeddingProvider | None = None


def _build_provider(config) -> EmbeddingProvider:  # noqa: ANN001
    section = _provider_section(config)
    provider = str(section.get("provider", "builtin") or "builtin").lower()
    dim = int(section.get("dim", 512) or 512)
    if provider == "onnx":
        resolve = getattr(config, "resolve_path", None)
        model_path = resolve(str(section.get("model_path", ""))) if resolve else section.get("model_path", "")
        return OnnxZhEmbedding(model_path)
    if provider == "api":
        return ApiEmbedding(
            base_url=str(section.get("api_base_url", "") or ""),
            api_key=str(section.get("api_key", "") or ""),
            model=str(section.get("api_model", "") or ""),
            timeout=float(section.get("api_timeout", 10) or 10),
            batch=int(section.get("api_batch", 16) or 16),
        )
    return BuiltinEmbedding(dim=dim)


def get_embedding_provider(config=None) -> EmbeddingProvider:  # noqa: ANN001
    """获取进程级 provider 单例；配置了不可用的 onnx/api 时降级 builtin。"""
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER
    if config is None:
        from backend.core.config_loader import get_config

        config = get_config()
    section = _provider_section(config)
    provider_name = str(section.get("provider", "builtin") or "builtin").lower()
    try:
        _PROVIDER = _build_provider(config)
    except Exception as exc:  # noqa: BLE001 - 显式配置不可用时降级，不阻断启动
        if provider_name != "builtin":
            logger.error(
                "embedding provider=%s 初始化失败（%s），已降级为内置 builtin 向量；"
                "请检查依赖 / 模型路径 / API 配置后重启",
                provider_name, exc,
            )
        _PROVIDER = BuiltinEmbedding(dim=int(section.get("dim", 512) or 512))
    logger.info(
        "embedding provider 就绪：%s（signature=%s）",
        _PROVIDER.name, _PROVIDER.signature,
    )
    return _PROVIDER


def reset_embedding_provider_cache() -> None:
    """测试 / 配置切换时重置单例。"""
    global _PROVIDER
    provider = _PROVIDER
    _PROVIDER = None
    if isinstance(provider, ApiEmbedding):
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(provider.close())
        except RuntimeError:
            pass
