"""Cross-tenant credentials and sandbox lifecycle boundaries."""

import base64
import hashlib
import hmac
import time
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import SecretStr
from starlette.requests import Request

from app.core.config import settings
from app.core.auth import get_current_user_id
from app.core.tenant_credentials import (
    gateway_secret,
    provider_token,
    token_secret,
    verify_provider_token,
)
from app.core.user_token import create_user_token, verify_user_token
from app.gateway.sandbox_manager import SandboxManager, _safe_user_id


@pytest.fixture
def credentials(monkeypatch):
    monkeypatch.setattr(settings, "EIDO_GATEWAY_SECRET", "gateway-master-unique-secret")
    monkeypatch.setattr(settings, "SESSION_SECRET_KEY", "session-master-unique-secret")
    monkeypatch.setattr(settings, "EIDO_USER_TOKEN_SECRET", "token-master-unique-secret")
    monkeypatch.setattr(settings, "EIDO_TRUST_GATEWAY", False)


def test_tenant_cannot_mint_other_identity(credentials, monkeypatch):
    alice_secret = token_secret("alice")
    alice_token = create_user_token("alice")
    bob_token = create_user_token("bob")
    assert gateway_secret("alice") != gateway_secret("bob")
    assert alice_secret != gateway_secret("alice")
    monkeypatch.setattr(settings, "EIDO_TRUST_GATEWAY", True)
    monkeypatch.setattr(settings, "EIDO_USER_ID", "alice")
    monkeypatch.setattr(settings, "EIDO_USER_TOKEN_SECRET", alice_secret)
    assert verify_user_token(alice_token) == "alice"
    assert verify_user_token(create_user_token("alice")) == "alice"
    for action in (lambda: create_user_token("bob"), lambda: verify_user_token(bob_token)):
        with pytest.raises(ValueError):
            action()
    # Even hand-crafted signatures using the exposed tenant key fail at gateway.
    payload = f"bob:{int(time.time()) + 60}"
    signature = hmac.new(alice_secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    forged = base64.urlsafe_b64encode(f"{payload}:{signature}".encode()).decode()
    monkeypatch.setattr(settings, "EIDO_TRUST_GATEWAY", False)
    monkeypatch.setattr(settings, "EIDO_USER_TOKEN_SECRET", "token-master-unique-secret")
    with pytest.raises(ValueError):
        verify_user_token(forged)


def test_sandbox_rejects_cookie_and_wrong_bound_identity(credentials, monkeypatch):
    monkeypatch.setattr(settings, "EIDO_TRUST_GATEWAY", True)
    monkeypatch.setattr(settings, "EIDO_USER_ID", "alice")
    monkeypatch.setattr(settings, "EIDO_GATEWAY_SECRET", "alice-secret")

    def request(user):
        return Request(
            {
                "type": "http",
                "headers": [
                    (b"x-eido-user-id", user.encode()),
                    (b"x-eido-gateway-secret", b"alice-secret"),
                ],
                "session": {"user_id": "bob"},
            }
        )

    assert get_current_user_id(request("alice")) == "alice"
    with pytest.raises(HTTPException) as caught:
        get_current_user_id(request("bob"))
    assert caught.value.status_code == 401


def test_provider_token_is_identity_and_purpose_bound(credentials):
    token = provider_token("alice")
    assert verify_provider_token(token) == "alice"
    encoded_bob = base64.urlsafe_b64encode(b"bob").decode().rstrip("=")
    for forged in (
        f"v1.{encoded_bob}.{token.split('.')[-1]}",
        "",
        "v1.invalid.no",
        gateway_secret("alice"),
    ):
        with pytest.raises(ValueError):
            verify_provider_token(forged)


def test_long_user_ids_do_not_collide():
    assert _safe_user_id("a" * 48 + "1") != _safe_user_id("a" * 48 + "2")


def test_gc_preserves_active_streams_and_native_tasks(tmp_path, monkeypatch):
    manager = SandboxManager(mode="local")
    manager._db_path = str(tmp_path / "registry.db")
    manager.connect()
    try:
        manager._upsert_row("alice", "alice", "eido-user-alice", "eido-user-alice")
        manager.retain("alice")
        assert not manager._stop_docker("alice", idle_before=time.time() + 1)
        manager.release("alice")
        monkeypatch.setattr(manager, "_runtime_busy", lambda _: True)
        assert not manager._stop_docker("alice", idle_before=time.time() + 1)

        # A new request during the health probe must also prevent collection.
        def became_active(user):
            manager.retain(user)
            return False

        monkeypatch.setattr(manager, "_runtime_busy", became_active)
        assert not manager._stop_docker("alice", idle_before=time.time() + 1)
    finally:
        manager.close()


@pytest.mark.asyncio
async def test_provider_relay_hides_master_and_forwards_reset(credentials, monkeypatch):
    from app.gateway import provider, sandbox_manager

    monkeypatch.setattr(settings, "ANTHROPIC_BASE_URL", "https://provider.example/anthropic")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("master-only"))
    monkeypatch.setattr(settings, "ANTHROPIC_AUTH_TOKEN", SecretStr(""))
    manager = MagicMock()
    monkeypatch.setattr(sandbox_manager, "get_sandbox_manager", lambda: manager)

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"error":"rate_limit"}\n\n'

    async def handler(request):
        assert str(request.url) == "https://provider.example/anthropic/v1/messages?beta=true"
        assert request.headers["x-api-key"] == "master-only"
        assert "authorization" not in request.headers
        assert "cookie" not in request.headers
        assert await request.aread() == b"{}"
        return httpx.Response(
            429, headers={"retry-after": "10", "content-type": "text/event-stream"}, stream=Stream()
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as upstream:
        monkeypatch.setattr(provider, "get_proxy_client", lambda: upstream)
        app = FastAPI()
        app.include_router(provider.router)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://gateway"
        ) as client:
            denied = await client.post("/provider/v1/messages", json={})
            assert denied.status_code == 401
            denied_path = await client.post(
                "/provider/arbitrary",
                headers={"authorization": "Bearer " + provider_token("alice")},
            )
            assert denied_path.status_code == 404
            response = await client.post(
                "/provider/v1/messages?beta=true",
                content=b"{}",
                headers={
                    "authorization": "Bearer " + provider_token("alice"),
                    "cookie": "secret=bad",
                },
            )
            assert response.status_code == 429
            assert response.headers["retry-after"] == "10"
            assert "rate_limit" in response.text
    manager.retain.assert_called_once_with("alice")
    manager.release.assert_called_once_with("alice")


@pytest.mark.asyncio
async def test_scheduled_script_is_forwarded_to_owner_container(monkeypatch):
    from app.services import task_executor, script_runner
    from app.gateway import proxy, sandbox_manager
    from unittest.mock import AsyncMock

    handle = object()
    manager = MagicMock()
    manager.ensure_running = AsyncMock(return_value=handle)
    monkeypatch.setattr(sandbox_manager, "get_sandbox_manager", lambda: manager)
    response = httpx.Response(
        200,
        json={"returncode": 0, "stdout": "tenant result", "stderr": ""},
        request=httpx.Request("POST", "http://tenant"),
    )
    forwarded = AsyncMock(return_value=response)
    monkeypatch.setattr(proxy, "proxy_internal_post", forwarded)
    monkeypatch.setattr(task_executor, "_is_docker_sandbox", lambda: True)
    monkeypatch.setattr(task_executor, "_append_task_message", AsyncMock())
    local = AsyncMock(side_effect=AssertionError("must never execute on gateway"))
    monkeypatch.setattr(script_runner, "run_script", local)
    await task_executor._execute_script(
        {
            "user_id": "alice",
            "type": "script",
            "params": {"script_path": "/bin/echo", "args": ["hello"]},
        },
        "session1",
    )
    manager.ensure_running.assert_awaited_once_with("alice")
    assert forwarded.call_args.kwargs["json_body"] == {
        "session_id": "session1",
        "command": ["/bin/echo", "hello"],
    }
    local.assert_not_called()
