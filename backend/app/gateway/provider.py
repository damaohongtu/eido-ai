"""Anthropic-compatible streaming relay. Only the gateway holds provider credentials."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.tenant_credentials import verify_provider_token
from app.gateway.proxy import get_proxy_client

router = APIRouter()
_ALLOWED = {("POST", "v1/messages"), ("POST", "v1/messages/count_tokens"), ("GET", "v1/models")}


@router.api_route("/provider/{path:path}", methods=["GET", "POST"])
async def relay_provider(path: str, request: Request):
    if (request.method, path) not in _ALLOWED:
        raise HTTPException(404, "Unsupported provider endpoint")
    authorization = request.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ") or request.headers.get("x-api-key", "")
    try:
        user_id = verify_provider_token(token)
    except ValueError as exc:
        raise HTTPException(401, "Invalid provider credential") from exc
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.startswith("anthropic-") or key in {"content-type", "accept"}
    }
    headers["accept-encoding"] = "identity"
    if settings.ANTHROPIC_API_KEY.get_secret_value():
        headers["x-api-key"] = settings.ANTHROPIC_API_KEY.get_secret_value()
    if settings.ANTHROPIC_AUTH_TOKEN.get_secret_value():
        headers["authorization"] = f"Bearer {settings.ANTHROPIC_AUTH_TOKEN.get_secret_value()}"
    if "x-api-key" not in headers and "authorization" not in headers:
        raise HTTPException(503, "Provider credentials are not configured")
    base = settings.ANTHROPIC_BASE_URL.rstrip("/") or "https://api.anthropic.com"
    # The caller can select only the fixed API paths above, never an upstream host.
    url = f"{base}/{path}"
    if request.url.query:
        url += "?" + request.url.query
    from app.gateway.sandbox_manager import get_sandbox_manager

    manager = get_sandbox_manager()
    manager.retain(user_id)
    try:
        client = get_proxy_client()
        upstream = await client.send(
            client.build_request(request.method, url, headers=headers, content=request.stream()),
            stream=True,
        )
    except BaseException:
        manager.release(user_id)
        raise

    async def stream():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            manager.release(user_id)

    # Preserve rate-limit/reset headers so native Claude Code can honor backoff.
    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.startswith(("anthropic-", "x-ratelimit-", "ratelimit-"))
        or key in {"content-type", "retry-after", "request-id", "content-encoding"}
    }
    response_headers["X-Accel-Buffering"] = "no"
    return StreamingResponse(stream(), status_code=upstream.status_code, headers=response_headers)
