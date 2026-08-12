from pathlib import Path

from app.services.mcp_config_store import SECRET_SENTINEL, McpConfigStore


def test_mcp_store_encrypts_redacts_and_restores_secrets(tmp_path: Path):
    store = McpConfigStore(tmp_path / "mcp.db")
    store.connect()
    try:
        created = store.create_server(
            "u1",
            name="docs",
            transport="http",
            config={
                "type": "http",
                "url": "https://example.test/mcp",
                "headers": {"Authorization": "Bearer secret"},
            },
            enabled=True,
        )
        assert created["config"]["headers"]["Authorization"] == SECRET_SENTINEL
        assert b"Bearer secret" not in (tmp_path / "mcp.db").read_bytes()

        updated = store.update_server(
            "u1",
            created["id"],
            name="docs",
            transport="http",
            config={
                "type": "http",
                "url": "https://example.test/mcp-v2",
                "headers": {"Authorization": SECRET_SENTINEL},
            },
            enabled=True,
        )
        assert updated is not None
        servers, revision = store.sdk_servers("u1")
        assert revision
        assert servers["docs"]["headers"]["Authorization"] == "Bearer secret"
        assert servers["docs"]["url"].endswith("mcp-v2")
        assert store.sdk_servers("other") == ({}, "")
    finally:
        store.close()


def test_mcp_store_excludes_disabled_servers(tmp_path: Path):
    store = McpConfigStore(tmp_path / "mcp.db")
    store.connect()
    try:
        store.create_server(
            "u1",
            name="local",
            transport="stdio",
            config={"type": "stdio", "command": "python", "args": ["server.py"], "env": {}},
            enabled=False,
        )
        assert store.sdk_servers("u1") == ({}, "")
    finally:
        store.close()
