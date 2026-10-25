"""统一异常定义与 FastAPI 异常处理器。

约定：路由层 / 服务层只抛出 ``AppError`` 子类，由全局处理器统一转成
``{"code": "...", "message": "...", "detail": ...}`` 结构，HTTP 状态码保持语义化。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("yuexu.exception")


class AppError(Exception):
    """业务异常基类。"""

    code: str = "APP_ERROR"
    status_code: int = 400
    message: str = "请求处理失败"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        detail: object = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.detail = detail
        super().__init__(self.message)


class NotFoundError(AppError):
    code = "NOT_FOUND"
    status_code = 404
    message = "资源不存在"


class ConflictError(AppError):
    code = "CONFLICT"
    status_code = 409
    message = "资源冲突"


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    status_code = 422
    message = "参数校验失败"


class AuthError(AppError):
    code = "UNAUTHORIZED"
    status_code = 401
    message = "未登录或登录已过期"


class PermissionDeniedError(AppError):
    code = "FORBIDDEN"
    status_code = 403
    message = "没有操作权限"


class RateLimitedError(AppError):
    code = "RATE_LIMITED"
    status_code = 429
    message = "操作过于频繁，请稍后再试"


class ConfigError(AppError):
    code = "CONFIG_ERROR"
    status_code = 500
    message = "配置错误"


class ExternalServiceError(AppError):
    """外部服务异常基类（LLM / 搜索 / TTS / 适配器）。"""

    code = "EXTERNAL_SERVICE_ERROR"
    status_code = 502
    message = "外部服务调用失败"


class LLMError(ExternalServiceError):
    code = "LLM_ERROR"
    message = "大模型调用失败"


class SearchError(ExternalServiceError):
    code = "SEARCH_ERROR"
    message = "联网搜索失败"


class TTSError(ExternalServiceError):
    code = "TTS_ERROR"
    message = "语音合成失败"


class AdapterError(ExternalServiceError):
    code = "ADAPTER_ERROR"
    message = "平台适配器异常"


class MemoryStoreError(ExternalServiceError):
    code = "MEMORY_ERROR"
    message = "记忆库操作失败"


def _payload(code: str, message: str, detail: object = None) -> dict:
    body: dict = {"code": code, "message": message}
    if detail is not None:
        body["detail"] = detail
    return body


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。"""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            logger.error("业务异常 %s %s: %s", exc.code, request.url.path, exc.message)
        else:
            logger.warning("业务异常 %s %s: %s", exc.code, request.url.path, exc.message)
        return JSONResponse(
            status_code=exc.status_code,
            content=_payload(exc.code, exc.message, exc.detail),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        from fastapi.encoders import jsonable_encoder

        # 校验失败时不能把密钥或完整请求体回显到错误响应。
        errors = jsonable_encoder([
            {key: error[key] for key in ("type", "loc", "msg") if key in error}
            for error in exc.errors()
        ])
        message = "参数校验失败"
        if errors:
            first = errors[0]
            loc = ".".join(str(part) for part in first.get("loc", ()))
            message = f"{loc}: {first.get('msg', message)}"
        return JSONResponse(
            status_code=422,
            content=_payload("VALIDATION_ERROR", message, errors),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未捕获异常 %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content=_payload("INTERNAL_ERROR", "服务内部错误，请查看日志"),
        )
