"""Encrypted user-scoped MCP server configuration persistence."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

SECRET_SENTINEL = "__EIDO_SECRET__"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class McpConfigStore:
    """Store MCP credentials encrypted at rest and never return them to clients."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = Path(db_path or settings.mcp_servers_db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        key_path = self._db_path.parent / ".secrets" / "mcp-config.key"
        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            os.chmod(key_path, 0o600)
            key = key_path.read_bytes().strip()
        else:
            key = Fernet.generate_key()
            with os.fdopen(fd, "wb") as handle:
                handle.write(key)
        if not key:
            raise RuntimeError("MCP 配置加密密钥为空")
        return key

    def connect(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mcp_servers (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    transport TEXT NOT NULL CHECK(transport IN ('stdio', 'http', 'sse')),
                    config_encrypted BLOB NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(user_id, name)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_mcp_servers_user ON mcp_servers(user_id, updated_at DESC)"
            )
            conn.commit()
            self._conn = conn

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.connect()
        assert self._conn is not None
        return self._conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            conn = self.conn
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except Exception:
                conn.rollback()
                raise
            else:
                conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _encrypt(self, config: dict) -> bytes:
        raw = json.dumps(config, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return self._fernet.encrypt(raw)

    def _decrypt(self, value: bytes) -> dict:
        try:
            result = json.loads(self._fernet.decrypt(value).decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("MCP 配置无法解密，请检查持久化密钥") from exc
        if not isinstance(result, dict):
            raise RuntimeError("MCP 配置格式无效")
        return result

    @staticmethod
    def _redact(config: dict) -> dict:
        result = dict(config)
        for field in ("env", "headers"):
            values = result.get(field)
            if isinstance(values, dict):
                result[field] = {str(key): SECRET_SENTINEL for key in values}
        return result

    @staticmethod
    def _restore_secrets(config: dict, existing: Optional[dict]) -> dict:
        result = dict(config)
        for field in ("env", "headers"):
            values = result.get(field)
            if not isinstance(values, dict):
                continue
            old_values = (existing or {}).get(field) or {}
            restored: dict[str, str] = {}
            for key, value in values.items():
                key = str(key)
                if value == SECRET_SENTINEL:
                    if key not in old_values:
                        raise ValueError(
                            f"{field}.{key} 使用了 {SECRET_SENTINEL}，但没有可复用的已保存密钥"
                        )
                    restored[key] = old_values[key]
                else:
                    restored[key] = str(value)
            result[field] = restored
        return result

    def _row_to_dict(self, row: sqlite3.Row, *, reveal: bool = False) -> dict:
        config = self._decrypt(row["config_encrypted"])
        return {
            "id": row["id"],
            "name": row["name"],
            "transport": row["transport"],
            "config": config if reveal else self._redact(config),
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def list_servers(self, user_id: str) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM mcp_servers WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def get_server(self, user_id: str, server_id: str, *, reveal: bool = False) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM mcp_servers WHERE id = ? AND user_id = ?",
                (server_id, user_id),
            ).fetchone()
            return self._row_to_dict(row, reveal=reveal) if row else None

    def create_server(
        self, user_id: str, *, name: str, transport: str, config: dict, enabled: bool
    ) -> dict:
        server_id = uuid.uuid4().hex
        now = _now_iso()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO mcp_servers
                    (id, user_id, name, transport, config_encrypted, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (server_id, user_id, name, transport, self._encrypt(config), int(enabled), now, now),
            )
        return self.get_server(user_id, server_id)  # type: ignore[return-value]

    def update_server(
        self,
        user_id: str,
        server_id: str,
        *,
        name: str,
        transport: str,
        config: dict,
        enabled: bool,
    ) -> Optional[dict]:
        existing = self.get_server(user_id, server_id, reveal=True)
        if existing is None:
            return None
        restored = self._restore_secrets(config, existing["config"])
        with self._transaction() as conn:
            conn.execute(
                """
                UPDATE mcp_servers
                SET name = ?, transport = ?, config_encrypted = ?, enabled = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (name, transport, self._encrypt(restored), int(enabled), _now_iso(), server_id, user_id),
            )
        return self.get_server(user_id, server_id)

    def delete_server(self, user_id: str, server_id: str) -> bool:
        with self._transaction() as conn:
            cur = conn.execute(
                "DELETE FROM mcp_servers WHERE id = ? AND user_id = ?",
                (server_id, user_id),
            )
            return cur.rowcount > 0

    def replace_servers(self, user_id: str, servers: dict[str, dict]) -> list[dict]:
        """Atomically replace one user's full mcpServers document.

        Secret sentinels reuse the value stored under the same server name and
        env/header key. A transaction guarantees that invalid/new data never
        leaves a partially replaced configuration.
        """
        with self._transaction() as conn:
            existing_rows = conn.execute(
                "SELECT * FROM mcp_servers WHERE user_id = ?", (user_id,)
            ).fetchall()
            existing_by_name = {
                row["name"]: self._decrypt(row["config_encrypted"])
                for row in existing_rows
            }
            now = _now_iso()
            conn.execute("DELETE FROM mcp_servers WHERE user_id = ?", (user_id,))
            for name, item in servers.items():
                config = self._restore_secrets(
                    item["config"], existing_by_name.get(name)
                )
                conn.execute(
                    """
                    INSERT INTO mcp_servers
                        (id, user_id, name, transport, config_encrypted, enabled,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        user_id,
                        name,
                        item["transport"],
                        self._encrypt(config),
                        int(item["enabled"]),
                        now,
                        now,
                    ),
                )
        return self.list_servers(user_id)

    def sdk_servers(self, user_id: Optional[str]) -> tuple[dict[str, dict], str]:
        if not user_id:
            return {}, ""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM mcp_servers WHERE user_id = ? AND enabled = 1 ORDER BY name",
                (user_id,),
            ).fetchall()
            servers: dict[str, dict] = {}
            fingerprint: list[dict] = []
            for row in rows:
                config = self._decrypt(row["config_encrypted"])
                servers[row["name"]] = config
                fingerprint.append({"name": row["name"], "config": config})
        if not servers:
            return {}, ""
        revision = hashlib.sha256(
            json.dumps(fingerprint, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        return servers, revision


_instance: Optional[McpConfigStore] = None


def get_mcp_config_store() -> McpConfigStore:
    global _instance
    if _instance is None:
        _instance = McpConfigStore()
        _instance.connect()
    return _instance


def close_mcp_config_store() -> None:
    global _instance
    if _instance is not None:
        _instance.close()
        _instance = None
