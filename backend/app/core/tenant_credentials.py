"""Domain-separated tenant credentials; master secrets never enter user containers."""

import base64
import hashlib
import hmac

from app.core.config import settings


def derive_secret(master: str, purpose: str, user_id: str) -> str:
    if not master or not user_id:
        raise ValueError("Tenant credential requires a master secret and user ID")
    return hmac.new(
        master.encode(), f"eido-v1:{purpose}:{user_id}".encode(), hashlib.sha256
    ).hexdigest()


def gateway_secret(user_id: str) -> str:
    return derive_secret(settings.EIDO_GATEWAY_SECRET, "gateway", user_id)


def token_secret(user_id: str) -> str:
    if settings.EIDO_TRUST_GATEWAY:
        if user_id != settings.EIDO_USER_ID or not settings.EIDO_USER_TOKEN_SECRET:
            raise ValueError("Token identity does not match container")
        return settings.EIDO_USER_TOKEN_SECRET
    return derive_secret(settings.token_secret, "user-token", user_id)


def provider_token(user_id: str) -> str:
    encoded = base64.urlsafe_b64encode(user_id.encode()).decode().rstrip("=")
    signature = derive_secret(settings.EIDO_GATEWAY_SECRET, "provider", user_id)
    return f"v1.{encoded}.{signature}"


def verify_provider_token(token: str) -> str:
    try:
        version, encoded, signature = token.split(".")
        if version != "v1" or len(encoded) > 172:
            raise ValueError()
        user_id = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode()
        expected = derive_secret(settings.EIDO_GATEWAY_SECRET, "provider", user_id)
        if not hmac.compare_digest(expected, signature):
            raise ValueError()
        return user_id
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid provider credential") from exc
