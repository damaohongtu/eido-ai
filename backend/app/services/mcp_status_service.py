"""Live MCP health checks and tool discovery for the user's tool page."""
from __future__ import annotations

import asyncio
import ipaddress
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import httpx
from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from app.services.mcp_config_store import get_mcp_config_store

_CACHE_TTL_SECONDS = 30.0
_PROBE_TIMEOUT_SECONDS = 12.0
_MAX_CONCURRENT_PROBES = 6
_cache: dict[str, tuple[tuple, float, list[dict]]] = {}


def clear_mcp_status_cache(user_id: Optional[str] = None) -> None:
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(user_id, None)


def _is_loopback_url(url: str) -> bool:
    hostname = (urlsplit(url).hostname or "").lower()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _http_client_factory(*, direct: bool):
    def create_client(headers=None, timeout=None, auth=None):
        return httpx.AsyncClient(
            headers=headers,
            timeout=timeout,
            auth=auth,
            follow_redirects=True,
            trust_env=not direct,
        )

    return create_client


async def _list_tools(config: dict) -> list[dict[str, str]]:
    transport = config.get("type", "stdio")
    if transport == "stdio":
        params = StdioServerParameters(
            command=config["command"],
            args=config.get("args") or [],
            env=config.get("env") or None,
            cwd=Path.cwd(),
        )
        context = stdio_client(params)
    elif transport == "sse":
        url = config["url"]
        context = sse_client(
            url,
            headers=config.get("headers") or None,
            timeout=_PROBE_TIMEOUT_SECONDS,
            sse_read_timeout=_PROBE_TIMEOUT_SECONDS,
            httpx_client_factory=_http_client_factory(direct=_is_loopback_url(url)),
        )
    else:
        url = config["url"]
        context = streamablehttp_client(
            url,
            headers=config.get("headers") or None,
            timeout=_PROBE_TIMEOUT_SECONDS,
            sse_read_timeout=_PROBE_TIMEOUT_SECONDS,
            httpx_client_factory=_http_client_factory(direct=_is_loopback_url(url)),
        )

    async with context as streams:
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": (tool.description or "")[:240],
                }
                for tool in result.tools
            ]


def _safe_probe_error(error: BaseException) -> str:
    if isinstance(error, asyncio.TimeoutError):
        return "连接超时"
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    if isinstance(error, BaseExceptionGroup) and error.exceptions:
        return _safe_probe_error(error.exceptions[0])
    return f"连接失败（{type(error).__name__}）"


async def _probe_one(public: dict, config: dict) -> dict:
    base = {
        "id": public["id"],
        "name": public["name"],
        "transport": public["transport"],
        "enabled": public["enabled"],
        "target": config.get("url") or config.get("command") or "",
        "updated_at": public["updated_at"],
    }
    if not public["enabled"]:
        return {
            **base,
            "status": "disabled",
            "tool_count": 0,
            "tools": [],
            "error": None,
        }
    try:
        tools = await asyncio.wait_for(
            _list_tools(config), timeout=_PROBE_TIMEOUT_SECONDS
        )
        return {
            **base,
            "status": "connected",
            "tool_count": len(tools),
            "tools": tools,
            "error": None,
        }
    except Exception as exc:
        return {
            **base,
            "status": "error",
            "tool_count": 0,
            "tools": [],
            "error": _safe_probe_error(exc),
        }


async def get_mcp_server_statuses(user_id: str, *, refresh: bool = False) -> list[dict]:
    store = get_mcp_config_store()
    public_servers = store.list_servers(user_id)
    signature = tuple(
        (item["id"], item["updated_at"], item["enabled"]) for item in public_servers
    )
    cached = _cache.get(user_id)
    if (
        not refresh
        and cached is not None
        and cached[0] == signature
        and cached[1] > time.monotonic()
    ):
        return cached[2]

    runtime_by_id: dict[str, dict[str, Any]] = {}
    for item in public_servers:
        revealed = store.get_server(user_id, item["id"], reveal=True)
        if revealed is not None:
            runtime_by_id[item["id"]] = revealed["config"]

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PROBES)

    async def bounded_probe(item: dict) -> dict:
        async with semaphore:
            return await _probe_one(item, runtime_by_id.get(item["id"], {}))

    results = await asyncio.gather(
        *(bounded_probe(item) for item in public_servers)
    )
    _cache[user_id] = (signature, time.monotonic() + _CACHE_TTL_SECONDS, results)
    return results
