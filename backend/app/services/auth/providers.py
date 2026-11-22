"""Configure OAuth/OIDC clients and normalize their authenticated identities."""

from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth, StarletteOAuth2App
from pydantic import BaseModel, Field, HttpUrl, SecretStr, TypeAdapter
from starlette.requests import Request

from app.core.auth import ensure_github_account_allowed
from app.core.config import settings


class OIDCProviderConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    name: str
    issuer: HttpUrl
    client_id: str = Field(min_length=1)
    client_secret: SecretStr
    redirect_uri: HttpUrl | None = None
    scope: str = "openid profile"
    token_endpoint_auth_method: Literal["client_secret_basic", "client_secret_post"] = (
        "client_secret_basic"
    )


@dataclass(frozen=True)
class LoginProvider:
    id: str
    name: str
    client: StarletteOAuth2App
    redirect_uri: str

    async def authenticate(self, request: Request) -> tuple[str, str]:
        token = await self.client.authorize_access_token(request)
        if self.id == "github":
            response = await self.client.get("user", token=token)
            response.raise_for_status()
            profile = response.json()
            subject = profile.get("id")
            if not isinstance(subject, int) or subject <= 0:
                raise OAuthError("invalid_userinfo")
            login = profile.get("login")
            if not isinstance(login, str) or not login:
                raise OAuthError("invalid_userinfo")
            ensure_github_account_allowed(login)
            user_id = f"oauth_github_{subject}"
            name = profile.get("name") or login
        else:
            # Authlib verifies the ID token's signature, issuer, audience and nonce.
            profile = token.get("userinfo") or {}
            subject = profile.get("sub")
            issuer = profile.get("iss")
            if not isinstance(subject, str) or not subject or not issuer:
                raise OAuthError("invalid_userinfo")
            digest = sha256(f"{issuer}\0{subject}".encode()).hexdigest()[:32]
            user_id = f"oauth_{self.id}_{digest}"
            name = profile.get("name") or profile.get("preferred_username")
        return user_id, str(name or user_id)


def get_login_providers() -> dict[str, LoginProvider]:
    """Construct clients from deployment settings; credentials never leave the backend."""
    oauth = OAuth()
    providers: dict[str, LoginProvider] = {}
    callback_base = f"{settings.FRONTEND_URL.rstrip('/')}{settings.API_V1_STR}/auth/callback"
    if settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET.get_secret_value():
        client = oauth.register(
            "github",
            client_id=settings.GITHUB_CLIENT_ID,
            client_secret=settings.GITHUB_CLIENT_SECRET.get_secret_value(),
            authorize_url="https://github.com/login/oauth/authorize",
            access_token_url="https://github.com/login/oauth/access_token",
            api_base_url="https://api.github.com/",
            client_kwargs={
                "scope": "read:user",
                "code_challenge_method": "S256",
                "token_endpoint_auth_method": "client_secret_post",
                "timeout": 15,
            },
        )
        providers["github"] = LoginProvider(
            "github", "GitHub", client, settings.GITHUB_REDIRECT_URI or f"{callback_base}/github"
        )
    configs = TypeAdapter(list[OIDCProviderConfig]).validate_json(
        settings.OIDC_PROVIDERS_JSON.get_secret_value()
    )
    for config in configs:
        if config.id in {"cas", "github", "dev"} or config.id in providers:
            raise ValueError("认证提供方 ID 重复或使用了保留名称")
        if "openid" not in config.scope.split():
            raise ValueError("OIDC scope 必须包含 openid")
        client = oauth.register(
            config.id,
            client_id=config.client_id,
            client_secret=config.client_secret.get_secret_value(),
            server_metadata_url=f"{str(config.issuer).rstrip('/')}/.well-known/openid-configuration",
            client_kwargs={
                "scope": config.scope,
                "code_challenge_method": "S256",
                "token_endpoint_auth_method": config.token_endpoint_auth_method,
                "timeout": 15,
            },
        )
        providers[config.id] = LoginProvider(
            config.id,
            config.name,
            client,
            str(config.redirect_uri or f"{callback_base}/{config.id}"),
        )
    return providers
