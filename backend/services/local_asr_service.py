"""独立本地 SenseVoice CPU 服务，兼容月叙使用的 /api/v1/asr 请求。"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
import re
import threading
import wave

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
import numpy as np

logger = logging.getLogger("yuexu.local_asr")
MAX_SAMPLES = 16000 * 30


def _load_recognizer():
    import sherpa_onnx

    default = Path(__file__).resolve().parents[2] / "data/voice_call/asr/models"
    directory = Path(os.environ.get("YUEXU_ASR_MODEL_DIR", str(default)))
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(directory / "model.int8.onnx"), tokens=str(directory / "tokens.txt"),
        language="auto", use_itn=True, provider="cpu", num_threads=min(4, os.cpu_count() or 1),
    )


def _wav_samples(payload: bytes):
    try:
        with wave.open(io.BytesIO(payload), "rb") as audio:
            count = audio.getnframes()
            if (audio.getframerate() != 16000 or audio.getnchannels() != 1
                    or audio.getsampwidth() != 2 or audio.getcomptype() != "NONE"
                    or not 0 < count <= MAX_SAMPLES):
                raise ValueError
            pcm = audio.readframes(count)
            if len(pcm) != count * 2:
                raise ValueError
    except (wave.Error, EOFError, OSError, ValueError) as exc:
        raise HTTPException(422, "音频须为不超过 30 秒的 16kHz 单声道 16 位 PCM WAV") from exc
    return np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768


def create_app(recognizer=None) -> FastAPI:
    recognizer = recognizer if recognizer is not None else _load_recognizer()
    lock = threading.Lock()
    app = FastAPI(title="月叙本地 SenseVoice", version="1.0")

    @app.get("/health")
    def health():
        return {"status": "ok", "model": "SenseVoiceSmall", "provider": "cpu"}

    @app.post("/api/v1/asr")
    def transcribe(files: list[UploadFile] = File(...), keys: str = Form("call"),
                   lang: str = Form("auto"), use_itn: bool = Form(True)):
        if len(files) != 1 or lang != "auto" or not use_itn:
            raise HTTPException(422, "本地通话识别仅接受单个 WAV、lang=auto、use_itn=true")
        payload = files[0].file.read(MAX_SAMPLES * 2 + 65537)
        if len(payload) > MAX_SAMPLES * 2 + 65536:
            raise HTTPException(422, "音频文件过大")
        samples = _wav_samples(payload)
        try:
            # 同一识别器串行使用；同步路由由 FastAPI 在线程池执行，不阻塞 HTTP 事件循环。
            with lock:
                stream = recognizer.create_stream()
                stream.accept_waveform(16000, samples)
                recognizer.decode_stream(stream)
                text = re.sub(r"<\|[^<>]*\|>", "", stream.result.text).strip()
        except Exception as exc:
            logger.warning("本地语音识别失败（%s）", type(exc).__name__)
            raise HTTPException(503, "本地语音识别失败，请检查模型服务日志") from None
        return {"result": [{"key": keys, "text": text, "clean_text": text}]}

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=50000, access_log=False)
