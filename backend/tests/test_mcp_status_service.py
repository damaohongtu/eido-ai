from pathlib import Path

import pytest

from app.services import mcp_config_store as store_module
from app.services import mcp_status_service as status_module
from app.services.mcp_config_store import McpConfigStore


@pytest.mark.asyncio
async def test_status_reports_tool_counts_skips_disabled_and_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = McpConfigStore(tmp_path / "mcp.db")
    store.connect()
    monkeypatch.setattr(store_module, "_instance", store)
    status_module.clear_mcp_status_cache()
    try:
        store.create_server(
            "u1",
            name="enabled",
            transport="sse",
            config={"type": "sse", "url": "http://127.0.0.1:1234/sse"},
            enabled=True,
        )
        store.create_server(
            "u1",
            name="disabled",
            transport="http",
            config={"type": "http", "url": "https://example.test/mcp"},
            enabled=False,
        )
        calls = 0

        async def fake_list_tools(config):
            nonlocal calls
            calls += 1
            assert config["url"].endswith("/sse")
            return [
                {"name": "search", "description": "Search data"},
                {"name": "read", "description": "Read data"},
            ]

        monkeypatch.setattr(status_module, "_list_tools", fake_list_tools)
        first = await status_module.get_mcp_server_statuses("u1")
        by_name = {item["name"]: item for item in first}
        assert by_name["enabled"]["status"] == "connected"
        assert by_name["enabled"]["tool_count"] == 2
        assert by_name["disabled"]["status"] == "disabled"
        assert by_name["disabled"]["tool_count"] == 0
        assert calls == 1

        assert await status_module.get_mcp_server_statuses("u1") == first
        assert calls == 1
        await status_module.get_mcp_server_statuses("u1", refresh=True)
        assert calls == 2
    finally:
        status_module.clear_mcp_status_cache()
        store.close()
        store_module._instance = None


@pytest.mark.asyncio
async def test_status_sanitizes_probe_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    store = McpConfigStore(tmp_path / "mcp.db")
    store.connect()
    monkeypatch.setattr(store_module, "_instance", store)
    status_module.clear_mcp_status_cache()
    try:
        store.create_server(
            "u1",
            name="broken",
            transport="sse",
            config={
                "type": "sse",
                "url": "https://example.test/sse",
                "headers": {"Authorization": "must-not-leak"},
            },
            enabled=True,
        )

        async def fail(_config):
            raise RuntimeError("must-not-leak")

        monkeypatch.setattr(status_module, "_list_tools", fail)
        result = (await status_module.get_mcp_server_statuses("u1"))[0]
        assert result["status"] == "error"
        assert result["error"] == "连接失败（RuntimeError）"
        assert "must-not-leak" not in str(result)
    finally:
        status_module.clear_mcp_status_cache()
        store.close()
        store_module._instance = None
