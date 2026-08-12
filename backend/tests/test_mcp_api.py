from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.endpoints import mcp
from app.core.auth import get_current_user_id
from app.services import mcp_config_store as store_module
from app.services.mcp_config_store import SECRET_SENTINEL, McpConfigStore


@pytest.fixture
def mcp_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = McpConfigStore(tmp_path / "mcp.db")
    store.connect()
    monkeypatch.setattr(store_module, "_instance", store)
    monkeypatch.setattr(mcp, "_invalidate_user", lambda _user_id: None)
    identity = {"user_id": "u1"}
    app = FastAPI()
    app.include_router(mcp.router, prefix="/api/v1/mcp")
    app.dependency_overrides[get_current_user_id] = lambda: identity["user_id"]
    with TestClient(app) as client:
        yield client, identity, store
    store.close()
    store_module._instance = None


def test_mcp_api_is_user_scoped_and_redacts_secrets(mcp_api):
    client, identity, store = mcp_api
    created = client.post(
        "/api/v1/mcp/servers",
        json={
            "name": "research",
            "transport": "http",
            "url": "https://mcp.example.test/service",
            "headers": {"Authorization": "Bearer private"},
            "enabled": True,
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["config"]["headers"]["Authorization"] == SECRET_SENTINEL

    identity["user_id"] = "u2"
    assert client.get("/api/v1/mcp/servers").json() == []
    assert client.delete(f"/api/v1/mcp/servers/{body['id']}").status_code == 404

    servers, _revision = store.sdk_servers("u1")
    assert servers["research"]["headers"]["Authorization"] == "Bearer private"


def test_mcp_api_validates_transport_and_duplicate_names(mcp_api):
    client, _identity, _store = mcp_api
    invalid = client.post(
        "/api/v1/mcp/servers",
        json={"name": "bad name", "transport": "stdio", "command": ""},
    )
    assert invalid.status_code == 422

    payload = {
        "name": "local",
        "transport": "stdio",
        "command": "python",
        "args": ["server.py"],
    }
    assert client.post("/api/v1/mcp/servers", json=payload).status_code == 200
    duplicate = client.post("/api/v1/mcp/servers", json=payload)
    assert duplicate.status_code == 409


def test_mcp_config_file_replaces_atomically_and_maps_disabled(mcp_api):
    client, _identity, store = mcp_api
    config = {
        "mcpServers": {
            "comein-search": {
                "type": "sse",
                "url": "http://127.0.0.1:16666/ia-mcp-proxy/comein-mcp/sse",
                "headers": {"x-mesh-auth": "123456"},
                "disabled": True,
            },
            "mao-mcp": {
                "type": "sse",
                "url": "http://127.0.0.1:16666/ia-mcp-proxy/mao-mcp/sse",
                "headers": {"x-mesh-auth": "123456"},
                "disabled": False,
            },
        }
    }
    saved = client.put("/api/v1/mcp/config", json=config)
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["mcpServers"]["comein-search"]["disabled"] is True
    assert body["mcpServers"]["mao-mcp"]["disabled"] is False
    assert (
        body["mcpServers"]["mao-mcp"]["headers"]["x-mesh-auth"]
        == SECRET_SENTINEL
    )

    sdk_servers, _revision = store.sdk_servers("u1")
    assert set(sdk_servers) == {"mao-mcp"}
    assert sdk_servers["mao-mcp"]["headers"]["x-mesh-auth"] == "123456"

    resaved = client.put("/api/v1/mcp/config", json=body)
    assert resaved.status_code == 200, resaved.text
    sdk_servers, _revision = store.sdk_servers("u1")
    assert sdk_servers["mao-mcp"]["headers"]["x-mesh-auth"] == "123456"

    invalid = client.put(
        "/api/v1/mcp/config",
        json={
            "mcpServers": {
                "new-server": {
                    "type": "http",
                    "url": "https://example.test/mcp",
                    "headers": {"Authorization": SECRET_SENTINEL},
                }
            }
        },
    )
    assert invalid.status_code == 422
    assert set(store.sdk_servers("u1")[0]) == {"mao-mcp"}
