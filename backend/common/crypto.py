"""密码哈希与 JWT 令牌工具（纯标准库 + PyJWT，无原生依赖）。"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

from backend.common.exceptions import AuthError

_PBKDF2_ITERATIONS = 120_000
_PREFIX = "pbkdf2_sha256"


def hash_password(password: str, iterations: int = _PBKDF2_ITERATIONS) -> str:
    """PBKDF2-HMAC-SHA256 哈希，格式：pbkdf2_sha256$iterations$salt$hash。"""
    if not password:
        raise ValueError("密码不能为空")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), iterations
    ).hex()
    return f"{_PREFIX}${iterations}${salt}${digest}"


def verify_password(password: str, stored: str | None) -> bool:
    if not password or not stored:
        return False
    try:
        prefix, iterations, salt, digest = stored.split("$", 3)
        if prefix != _PREFIX:
            return False
        computed = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
        ).hex()
        return hmac.compare_digest(computed, digest)
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str,
    *,
    secret: str,
    minutes: int = 720,
    algorithm: str = "HS256",
    role: str = "user",
    extra: dict[str, Any] | None = None,
) -> str:
    """签发访问令牌。"""
    issued_at = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "type": "access",
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=max(1, minutes)),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, secret, algorithm=algorithm)


def decode_access_token(token: str, *, secret: str, algorithm: str = "HS256") -> dict[str, Any]:
    """解析并校验访问令牌，失败统一抛 AuthError。"""
    try:
        payload = jwt.decode(token, secret, algorithms=[algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise AuthError("登录已过期，请重新登录") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthError("登录凭证无效") from exc
    if payload.get("type") != "access":
        raise AuthError("登录凭证类型错误")
    return payload


def mask_secret(value: str | None, keep: int = 4) -> str:
    """密钥脱敏，供前端展示。"""
    if not value:
        return ""
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}{'*' * (len(value) - keep * 2)}{value[-keep:]}"
