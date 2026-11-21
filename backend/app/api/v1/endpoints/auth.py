"""
Authentication endpoints: login, callback, logout, me.

支持两种模式：
- ``AUTH_MODE=cas``（默认）：跳转 CAS 单点登录。
- ``AUTH_MODE=local``：本地账号密码（PBKDF2 哈希校验），无需外部认证服务。
"""

import hmac
import logging
from urllib.parse import quote, urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.core.config import settings
from app.core.local_auth import LoginThrottle, verify_password

router = APIRouter()
logger = logging.getLogger(__name__)

_login_throttle = LoginThrottle(max_failures=10, window_seconds=300)

_LOGIN_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>登录 · Eido AI</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: #0f1117; color: #e6e8ee; padding: 24px;
  }
  .card {
    width: 100%; max-width: 360px; background: #171a23;
    border: 1px solid #2a2f3d; border-radius: 12px; padding: 36px 28px;
  }
  h1 { font-size: 22px; font-weight: 600; margin-bottom: 6px; }
  .sub { font-size: 13px; color: #8a91a3; margin-bottom: 28px; }
  input {
    width: 100%; padding: 11px 13px; margin-bottom: 14px;
    background: #0f1117; border: 1px solid #2a2f3d; border-radius: 8px;
    color: #e6e8ee; font-size: 15px; outline: none;
  }
  input:focus { border-color: #4a7dff; }
  button {
    width: 100%; padding: 12px; margin-top: 4px; font-size: 15px;
    background: #2f5fe0; color: #fff; border: none; border-radius: 8px;
    cursor: pointer; font-weight: 500;
  }
  button:hover { background: #3a6cf0; }
  .error {
    display: none; margin-bottom: 16px; padding: 10px 12px;
    background: rgba(224, 74, 74, 0.12); border: 1px solid rgba(224, 74, 74, 0.4);
    border-radius: 8px; font-size: 13px; color: #ff8a8a;
  }
</style>
</head>
<body>
<main class="card">
  <h1>Eido AI</h1>
  <p class="sub">请输入账号密码登录</p>
  <p class="error" id="err"></p>
  <form method="post">
    <input name="username" placeholder="账号" autocomplete="username" required autofocus>
    <input name="password" type="password" placeholder="密码" autocomplete="current-password" required>
    <button type="submit">登 录</button>
  </form>
</main>
<script>
  const msg = new URLSearchParams(location.search).get("error") ||
              new URLSearchParams(location.search).get("locked");
  if (msg) {
    const el = document.getElementById("err");
    el.textContent = msg === "locked" ? "尝试过于频繁，请 5 分钟后再试" : "账号或密码错误，请重试";
    el.style.display = "block";
  }
</script>
</body>
</html>
"""


def _render_login_page() -> HTMLResponse:
    return HTMLResponse(content=_LOGIN_PAGE, status_code=200)


def _client_ip(request: Request) -> str:
    """取真实客户端 IP（容器内 nginx 反代时 uvicorn 只见 127.0.0.1）。"""
    forwarded = request.headers.get("X-Real-IP") or request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _login_redirect_url(flag: str, next_url: str | None = None) -> str:
    """登录页外部完整地址（nginx 会剥离 /ai-eido 前缀，不能用 request.url.path）。"""
    url = f"{settings.FRONTEND_URL.rstrip('/')}/api/v1/auth/login?{flag}=1"
    if next_url:
        url += f"&next={quote(next_url, safe='')}"
    return url


def _safe_next(raw: str | None) -> str | None:
    """登录后回跳地址：仅允许 FRONTEND_URL 同前缀的站内相对路径，防开放重定向。"""
    if not raw:
        return None
    prefix = urlparse(settings.FRONTEND_URL).path or "/"
    if raw.startswith(prefix) and "\\" not in raw and len(raw) < 512:
        return raw
    return None


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
    """Redirect user to CAS login page (or show local login form / auto-login)."""
    if settings.AUTH_MODE == "local":
        return _render_login_page()

    if settings.AUTH_DISABLED:
        request.session["user_id"] = settings.DEFAULT_DEV_USER_ID
        request.session["username"] = settings.DEFAULT_DEV_USER_ID
        return RedirectResponse(url=settings.FRONTEND_URL)

    client = _get_cas_client()
    login_url = client.get_login_url()
    return RedirectResponse(url=login_url)


@router.post("/login")
async def login_submit(request: Request):
    """AUTH_MODE=local：校验账号密码，签发 session。"""
    if settings.AUTH_MODE != "local":
        raise HTTPException(status_code=404, detail="未启用本地登录")

    next_url = _safe_next(request.query_params.get("next"))
    ip = _client_ip(request)
    if _login_throttle.is_blocked(ip):
        return RedirectResponse(url=_login_redirect_url("locked", next_url), status_code=303)

    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))

    user_ok = hmac.compare_digest(username, settings.LOCAL_AUTH_USERNAME)
    pass_ok = verify_password(password, settings.LOCAL_AUTH_PASSWORD_HASH.get_secret_value())
    if not (user_ok and pass_ok):
        _login_throttle.record_failure(ip)
        logger.warning("本地登录失败: ip=%s username=%r", ip, username[:32])
        return RedirectResponse(url=_login_redirect_url("error", next_url), status_code=303)

    _login_throttle.reset(ip)
    request.session["user_id"] = username
    request.session["username"] = username
    logger.info("本地登录成功: %s (ip=%s)", username, ip)
    return RedirectResponse(url=next_url or f"{settings.FRONTEND_URL}?login=success", status_code=303)


@router.get("/callback")
async def callback(request: Request, ticket: str = ""):
    """CAS callback: validate ticket, create session, redirect to frontend."""
    if settings.AUTH_MODE == "local":
        # 本地模式的 session 在 POST /login 签发，CAS 回调不再使用
        return RedirectResponse(url=settings.FRONTEND_URL)

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
    """Clear session and redirect to CAS logout (or frontend in local mode)."""
    request.session.clear()
    if settings.AUTH_DISABLED:
        return RedirectResponse(url=settings.FRONTEND_URL)
    if settings.AUTH_MODE == "local":
        next_url = _safe_next(request.query_params.get("next"))
        return RedirectResponse(url=next_url or settings.FRONTEND_URL)
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
