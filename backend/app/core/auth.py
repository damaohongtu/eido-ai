"""
Dependency helpers to resolve current user from:

1. Trusted gateway headers (only when EIDO_TRUST_GATEWAY=1)：
   X-Eido-User-Id + X-Eido-Gateway-Secret，由 gateway 注入到 user 沙箱容器。
2. 用户 API Key（X-API-Key），由网关或单机后端验证。
3. Session cookie（CAS 颁发）。
4. 自签短期 Token（X-Eido-User-Token），任务子进程使用。
"""

import logging

from fastapi import HTTPException, Request

from app.core.api_key import API_KEY_HEADER, verify_api_key
from app.core.config import settings
from app.core.user_token import verify_user_token

logger = logging.getLogger(__name__)


def _resolve_trusted_gateway_user(request: Request) -> str | None:
    """When running inside a per-user sandbox container, the gateway injects
    `X-Eido-User-Id` along with a shared secret. Only honor it if:
      - settings.EIDO_TRUST_GATEWAY is True
      - secret matches settings.EIDO_GATEWAY_SECRET (non-empty)
      - container's bound EIDO_USER_ID matches the header (when configured)
    Mismatch → log + fall through to other auth mechanisms (no 401 here)."""
    if not settings.EIDO_TRUST_GATEWAY:
        return None

    user_id = request.headers.get("X-Eido-User-Id")
    if not user_id:
        return None

    expected_secret = settings.EIDO_GATEWAY_SECRET.strip()
    if not expected_secret:
        logger.warning("EIDO_TRUST_GATEWAY 启用但未配置 EIDO_GATEWAY_SECRET，拒绝信任网关头")
        return None

    provided_secret = request.headers.get("X-Eido-Gateway-Secret", "")
    import hmac

    if not hmac.compare_digest(provided_secret, expected_secret):
        logger.warning("X-Eido-Gateway-Secret 不匹配，拒绝信任网关头 user=%s", user_id)
        return None

    bound = settings.EIDO_USER_ID.strip()
    if not bound or bound != user_id:
        logger.warning(
            "X-Eido-User-Id (%s) 与容器绑定 EIDO_USER_ID (%s) 不一致，拒绝", user_id, bound
        )
        return None

    return user_id


def get_current_user_id(request: Request) -> str:
    gateway_user = _resolve_trusted_gateway_user(request)
    if gateway_user:
        return gateway_user

    if not settings.EIDO_TRUST_GATEWAY and API_KEY_HEADER in request.headers:
        try:
            return verify_api_key(request.headers[API_KEY_HEADER])
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="API Key 无效") from exc

    user_id = request.session.get("user_id") if not settings.EIDO_TRUST_GATEWAY else None
    if user_id:
        return user_id

    token = request.headers.get("X-Eido-User-Token")
    if token:
        try:
            return verify_user_token(token)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Token 无效或已过期") from exc

    raise HTTPException(status_code=401, detail="未登录")
