"""
Signed short-lived tokens for passing user identity to task_cli.
Format: base64(user_id:expiry:hmac_hex)
"""
import base64
import hmac
import hashlib
import time

from app.core.config import settings


def create_user_token(user_id: str) -> str:
    expiry = int(time.time()) + settings.EIDO_USER_TOKEN_TTL
    payload = f"{user_id}:{expiry}"
    sig = hmac.new(
        settings.token_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{sig}".encode()).decode()


def verify_user_token(token: str) -> str:
    """Return user_id or raise ValueError."""
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
    except Exception as exc:
        raise ValueError("token 解码失败") from exc

    parts = decoded.split(":")
    if len(parts) != 3:
        raise ValueError("token 格式错误")

    user_id, expiry_str, sig = parts
    expected = hmac.new(
        settings.token_secret.encode(),
        f"{user_id}:{expiry_str}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(sig, expected):
        raise ValueError("token 签名无效")

    if int(expiry_str) < int(time.time()):
        raise ValueError("token 已过期")

    return user_id
