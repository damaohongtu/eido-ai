"""Login redirects, callbacks, browser sessions and API keys."""

import logging

import httpx
from authlib.integrations.base_client.errors import OAuthError
from authlib.jose.errors import JoseError
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.core.api_key import issue_api_key
from app.core.auth import ensure_user_allowed
from app.core.config import settings
from app.services.auth.cas import display_username, get_cas_client
from app.services.auth.providers import LoginProvider, get_login_providers

router = APIRouter()
logger = logging.getLogger(__name__)


def _login_redirect(request: Request, user_id: str, username: str, provider: str):
    ensure_user_allowed(user_id)
    request.session.clear()
    request.session.update(user_id=user_id, username=username, auth_provider=provider)
    logger.info("登录成功 provider=%s user=%s", provider, user_id)
    return RedirectResponse(url=f"{settings.FRONTEND_URL}?login=success")


def _oauth_providers() -> dict[str, LoginProvider]:
    try:
        return get_login_providers()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="认证提供方配置无效") from exc


def _oauth_provider(provider: str) -> LoginProvider:
    client = _oauth_providers().get(provider)
    if client is None:
        raise HTTPException(status_code=404, detail="认证提供方未启用")
    return client


def _cas_configured() -> bool:
    return bool(settings.CAS_SERVER_URL.strip() and settings.CAS_SERVICE_URL.strip())


def _cas_client(*, internal: bool = False):
    if not _cas_configured():
        raise HTTPException(status_code=503, detail="CAS 登录尚未配置")
    return get_cas_client(internal=internal)


@router.get("/providers")
async def list_providers():
    if settings.AUTH_DISABLED:
        return [{"id": "dev", "name": "开发模式"}]
    cas = [{"id": "cas", "name": "CAS"}] if _cas_configured() else []
    return cas + [
        {"id": provider.id, "name": provider.name} for provider in _oauth_providers().values()
    ]


@router.get("/login")
async def login(request: Request):
    """Redirect the browser to CAS login."""
    if settings.AUTH_DISABLED:
        return _login_redirect(
            request, settings.DEFAULT_DEV_USER_ID, settings.DEFAULT_DEV_USER_ID, "dev"
        )

    client = _cas_client()
    login_url = client.get_login_url()
    return RedirectResponse(url=login_url)


@router.get("/callback")
async def callback(request: Request, ticket: str = ""):
    """CAS callback: validate ticket, create session, redirect to frontend."""
    if settings.AUTH_DISABLED:
        return _login_redirect(
            request, settings.DEFAULT_DEV_USER_ID, settings.DEFAULT_DEV_USER_ID, "dev"
        )

    if not ticket:
        raise HTTPException(status_code=400, detail="缺少 ticket 参数")

    client = _cas_client(internal=True)
    user, attributes, _pgtiou = client.verify_ticket(ticket)

    if not user:
        raise HTTPException(status_code=401, detail="CAS ticket 验证失败")

    return _login_redirect(request, user, display_username(user, attributes), "cas")


@router.get("/login/{provider}")
async def oauth_login(provider: str, request: Request):
    login_provider = _oauth_provider(provider)
    try:
        return await login_provider.client.authorize_redirect(request, login_provider.redirect_uri)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="认证服务暂不可用") from exc


@router.get("/callback/{provider}")
async def oauth_callback(provider: str, request: Request):
    login_provider = _oauth_provider(provider)
    try:
        user_id, username = await login_provider.authenticate(request)
    except (OAuthError, JoseError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="登录验证失败，请重新登录") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="认证服务暂不可用") from exc
    return _login_redirect(request, user_id, username, provider)


@router.get("/logout")
async def logout(request: Request):
    """Clear the browser session; CAS sessions also use CAS logout."""
    provider = request.session.get("auth_provider", "cas")
    request.session.clear()
    if settings.AUTH_DISABLED or provider != "cas" or not _cas_configured():
        return RedirectResponse(url=settings.FRONTEND_URL)
    client = _cas_client()
    logout_url = client.get_logout_url(redirect_url=settings.FRONTEND_URL)
    return RedirectResponse(url=logout_url)


@router.get("/me")
async def me(request: Request):
    """Return current logged-in user info. Always requires a valid session."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    ensure_user_allowed(user_id)
    return {
        "user_id": user_id,
        "username": request.session.get("username", user_id),
    }


@router.get("/api-key")
async def get_api_key(request: Request, response: Response) -> dict[str, str]:
    """Return the API key for the browser's authenticated login session."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    ensure_user_allowed(user_id)
    try:
        key = issue_api_key(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return {"api_key": key}
