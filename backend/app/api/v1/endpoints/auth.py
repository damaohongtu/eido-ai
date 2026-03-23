"""
CAS authentication endpoints: login, callback, logout, me.
"""
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


def _cas_display_username(principal: str, attributes: object) -> str:
    """从 CAS 属性中取展示名；无可用属性时用 principal（登录名）。"""
    if not isinstance(attributes, dict) or not attributes:
        return principal
    for key in ("cn", "displayName", "givenName", "name", "uid", "username"):
        raw = attributes.get(key)
        if raw is None:
            continue
        if isinstance(raw, bytes):
            s = raw.decode("utf-8", errors="replace").strip()
        else:
            s = str(raw).strip()
        if s:
            return s
    return principal


def _get_cas_client():
    from cas import CASClient  # type: ignore
    return CASClient(
        version=int(settings.CAS_VERSION),
        server_url=settings.CAS_SERVER_URL,
        service_url=settings.CAS_SERVICE_URL,
    )


@router.get("/login")
async def login(request: Request):
    """Redirect user to CAS login page (or auto-login in dev mode)."""
    if settings.AUTH_DISABLED:
        request.session["user_id"] = settings.DEFAULT_DEV_USER_ID
        request.session["username"] = settings.DEFAULT_DEV_USER_ID
        return RedirectResponse(url=settings.FRONTEND_URL)

    client = _get_cas_client()
    login_url = client.get_login_url()
    return RedirectResponse(url=login_url)


@router.get("/callback")
async def callback(request: Request, ticket: str = ""):
    """CAS callback: validate ticket, create session, redirect to frontend."""
    if settings.AUTH_DISABLED:
        request.session["user_id"] = settings.DEFAULT_DEV_USER_ID
        request.session["username"] = settings.DEFAULT_DEV_USER_ID
        return RedirectResponse(url=settings.FRONTEND_URL)

    if not ticket:
        raise HTTPException(status_code=400, detail="缺少 ticket 参数")

    client = _get_cas_client()
    user, attributes, _pgtiou = client.verify_ticket(ticket)

    if not user:
        raise HTTPException(status_code=401, detail="CAS ticket 验证失败")

    request.session["user_id"] = user
    request.session["username"] = _cas_display_username(user, attributes)
    logger.info(f"CAS 登录成功: {user}")
    redirect_url = f"{settings.FRONTEND_URL}?login=success"
    return RedirectResponse(url=redirect_url)


@router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to CAS logout."""
    request.session.clear()
    if settings.AUTH_DISABLED:
        return RedirectResponse(url=settings.FRONTEND_URL)
    client = _get_cas_client()
    logout_url = client.get_logout_url(redirect_url=settings.FRONTEND_URL)
    return RedirectResponse(url=logout_url)


@router.get("/me")
async def me(request: Request):
    """Return current logged-in user info. Always requires a valid session."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录")
    return {
        "user_id": user_id,
        "username": request.session.get("username", user_id),
    }
