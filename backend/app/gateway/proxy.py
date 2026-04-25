"""
Reverse proxy helpers — gateway → per-user sandbox container.

特性：
- 透传 SSE（text/event-stream）：禁止缓冲、保留 transport 流式，header 设置 X-Accel-Buffering: no
- 透传 multipart 上传与文件下载（流式 read/write，避免内存放大）
- 注入 X-Eido-User-Id + X-Eido-Gateway-Secret，供 user 容器走"信任网关头"分支
- 复用 httpx.AsyncClient 单例（连接池长期复用，避免 SSE 期间连接频繁重建）
"""
from __future__ import annotations

import logging
from typing import AsyncIterator, Optional

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import StreamingResponse, Response

from app.core.config import settings
from app.gateway.sandbox_manager import SandboxHandle

logger = logging.getLogger(__name__)


_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


_client: Optional[httpx.AsyncClient] = None


def get_proxy_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        timeout = httpx.Timeout(connect=5.0, read=None, write=60.0, pool=5.0)
        limits = httpx.Limits(max_connections=200, max_keepalive_connections=64)
        _client = httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=False)
    return _client


async def close_proxy_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


_STRIP_INCOMING = {
    "cookie",
    # 防客户端伪造受信网关头：必须由 gateway 重新注入
    "x-eido-user-id",
    "x-eido-gateway-secret",
    "x-eido-user-token",
    "x-forwarded-user",
}


def _filter_request_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for k, v in request.headers.items():
        lk = k.lower()
        if lk in _HOP_BY_HOP:
            continue
        if lk in _STRIP_INCOMING:
            continue
        headers[k] = v
    return headers


def _filter_response_headers(resp: httpx.Response) -> dict[str, str]:
    headers: dict[str, str] = {}
    for k, v in resp.headers.items():
        if k.lower() in _HOP_BY_HOP:
            continue
        # Content-Encoding 已被 httpx 解码，去除以防客户端二次解码
        if k.lower() == "content-encoding":
            continue
        headers[k] = v
    return headers


def inject_trust_headers(headers: dict[str, str], user_id: str) -> dict[str, str]:
    """给透传到 user 容器的请求注入受信网关头。"""
    headers = dict(headers)
    headers["X-Eido-User-Id"] = user_id
    headers["X-Eido-Gateway-Secret"] = settings.EIDO_GATEWAY_SECRET
    headers.setdefault("X-Forwarded-User", user_id)
    return headers


_inject_trust_headers = inject_trust_headers  # 兼容旧引用


async def _aiter_request_body(request: Request) -> AsyncIterator[bytes]:
    async for chunk in request.stream():
        if chunk:
            yield chunk


async def proxy_request(
    request: Request,
    handle: SandboxHandle,
    *,
    upstream_path: str,
) -> Response:
    """通用反代：根据 Accept / Content-Type 自动选择 streaming 或 buffered 模式。"""
    upstream_url = f"{handle.base_url}{upstream_path}"
    if request.url.query:
        upstream_url = f"{upstream_url}?{request.url.query}"

    headers = inject_trust_headers(_filter_request_headers(request), handle.user_id)
    method = request.method.upper()

    accept = request.headers.get("accept", "")
    is_sse = "text/event-stream" in accept

    client = get_proxy_client()

    body_iter: AsyncIterator[bytes] | None = None
    if method not in ("GET", "HEAD", "DELETE"):
        body_iter = _aiter_request_body(request)

    try:
        req = client.build_request(
            method=method,
            url=upstream_url,
            headers=headers,
            content=body_iter,
        )
        upstream_resp = await client.send(req, stream=True)
    except httpx.ConnectError as e:
        logger.warning(f"sandbox 不可达 {upstream_url}: {e}")
        raise HTTPException(status_code=502, detail=f"sandbox 不可达: {e}")
    except httpx.HTTPError as e:
        logger.warning(f"代理失败 {upstream_url}: {e}")
        raise HTTPException(status_code=502, detail=f"代理失败: {e}")

    response_headers = _filter_response_headers(upstream_resp)

    upstream_ct = upstream_resp.headers.get("content-type", "")
    streaming = is_sse or "text/event-stream" in upstream_ct

    async def upstream_iterator() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream_resp.aiter_raw():
                if chunk:
                    yield chunk
        finally:
            await upstream_resp.aclose()

    if streaming:
        # SSE 必须的几条 header
        response_headers["Cache-Control"] = "no-cache, no-transform"
        response_headers["X-Accel-Buffering"] = "no"
        response_headers.setdefault("Connection", "keep-alive")

        async def streaming_iter() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream_resp.aiter_raw():
                    if chunk:
                        yield chunk
            finally:
                await upstream_resp.aclose()
                # 流结束后再刷一次 last_active_at，避免长 SSE 中途被 GC 回收
                try:
                    from app.gateway.sandbox_manager import get_sandbox_manager
                    get_sandbox_manager().release(handle.user_id)
                except Exception:
                    pass

        return StreamingResponse(
            streaming_iter(),
            status_code=upstream_resp.status_code,
            headers=response_headers,
            media_type=upstream_resp.headers.get("content-type", "text/event-stream"),
        )

    # 非流式：读取完整 body 后释放上游
    body = await upstream_resp.aread()
    await upstream_resp.aclose()
    return Response(
        content=body,
        status_code=upstream_resp.status_code,
        headers=response_headers,
        media_type=upstream_resp.headers.get("content-type"),
    )


async def proxy_internal_post(
    handle: SandboxHandle,
    *,
    upstream_path: str,
    json_body: Optional[dict] = None,
    user_id: Optional[str] = None,
) -> httpx.Response:
    """用于调度器内部触发：完整缓冲消费上游响应。"""
    headers = inject_trust_headers({}, user_id or handle.user_id)
    headers["Content-Type"] = "application/json"
    upstream_url = f"{handle.base_url}{upstream_path}"
    client = get_proxy_client()
    return await client.post(upstream_url, json=json_body or {}, headers=headers)
