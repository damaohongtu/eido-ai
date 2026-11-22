"""Domain-separated tenant credentials; master secrets never enter user containers."""

import base64
import hashlib
import hmac
import re

from app.core.config import settings

_USER_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_SAFE_REPLACE_RE = re.compile(r"[^A-Za-z0-9_\-]")


def safe_user_id(user_id: str) -> str:
    """Return the stable tenant name used by storage paths and sandboxes."""
    if not user_id:
        raise ValueError("user_id 为空")
    if _USER_ID_RE.fullmatch(user_id) and len(user_id) <= 48:
        return user_id
    base = _SAFE_REPLACE_RE.sub("-", user_id)[:32].strip("-") or "user"
    suffix = hashlib.sha1(user_id.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{suffix}"


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
