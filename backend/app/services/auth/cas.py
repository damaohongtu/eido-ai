"""CAS ticket validation and display names."""

from cas import CASClient

from app.core.config import settings


def get_cas_client(*, internal: bool = False):
    return CASClient(
        version=int(settings.CAS_VERSION),
        server_url=(settings.CAS_INTERNAL_URL or settings.CAS_SERVER_URL)
        if internal
        else settings.CAS_SERVER_URL,
        service_url=settings.CAS_SERVICE_URL,
    )


def display_username(principal: str, attributes: object) -> str:
    if isinstance(attributes, dict):
        for key in ("cn", "displayName", "givenName", "name", "uid", "username"):
            value = attributes.get(key)
            if value is not None:
                name = (
                    value.decode("utf-8", errors="replace")
                    if isinstance(value, bytes)
                    else str(value)
                ).strip()
                if name:
                    return name
    return principal
