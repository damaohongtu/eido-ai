"""Stable, deployment-scoped credentials for the public Eido API."""

from hashlib import sha256

from itsdangerous import BadData, URLSafeSerializer

from app.core.config import settings

API_KEY_HEADER = "X-API-Key"
_PREFIX = "eido_v1_"


def _serializer() -> URLSafeSerializer:
    secret = settings.SESSION_SECRET_KEY.strip()
    if settings.AUTH_DISABLED:
        raise ValueError("请启用登录认证后使用 API Key")
    if settings.EIDO_TRUST_GATEWAY or secret in ("", "dev-secret-change-in-production"):
        raise ValueError("请配置独立的 SESSION_SECRET_KEY 后启用 API Key")
    return URLSafeSerializer(
        secret, salt="eido-public-api-v1", signer_kwargs={"digest_method": sha256}
    )


def issue_api_key(user_id: str) -> str:
    return _PREFIX + _serializer().dumps(user_id)


def verify_api_key(key: str) -> str:
    if len(key) > 2048 or not key.startswith(_PREFIX):
        raise ValueError("API Key 无效")
    try:
        user_id = _serializer().loads(key.removeprefix(_PREFIX))
    except BadData as exc:
        raise ValueError("API Key 无效") from exc
    if not isinstance(user_id, str) or not user_id:
        raise ValueError("API Key 无效")
    return user_id
