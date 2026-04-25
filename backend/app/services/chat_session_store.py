"""
SQLite 存储：会话（chat_sessions）+ 消息（chat_messages）。

- 所有写操作都按 user_id 过滤，杜绝跨用户访问
- session_id 由后端生成（uuid hex 12 位），与 session_workspace 共用同一字符空间
- extra_json 容纳 thinking / thinkingLog / executionSteps / references / workflowMermaid 等可变字段，
  避免后续频繁 ALTER TABLE
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


_SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '新建会话',
        skill_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_sessions_user
    ON chat_sessions(user_id, updated_at DESC);
    """,
    """
    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        extra_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        PRIMARY KEY (session_id, id),
        FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chat_messages_session
    ON chat_messages(session_id, created_at);
    """,
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _session_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "title": row["title"],
        "skill_id": row["skill_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _message_row_to_dict(row: sqlite3.Row) -> dict:
    extra: dict = {}
    raw = row["extra_json"] or "{}"
    try:
        extra = json.loads(raw)
    except Exception:
        extra = {}
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "extra": extra,
        "created_at": row["created_at"],
    }


class ChatSessionStore:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is not None:
            self._db_path = str(db_path)
        else:
            self._db_path = str(Path(settings.WORKSPACE_ROOT) / ".eido" / "chat_sessions.db")
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        for sql in _SCHEMA_SQL:
            self._conn.execute(sql)
        self._conn.commit()
        logger.info(f"ChatSessionStore connected: {self._db_path}")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("ChatSessionStore 未连接")
        return self._conn

    # -------------------- session 操作 -------------------- #

    def create_session(
        self, user_id: str, *, title: str = "新建会话", skill_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        sid = session_id or _new_id()
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO chat_sessions (id, user_id, title, skill_id, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (sid, user_id, title, skill_id, now, now),
        )
        self.conn.commit()
        return self.get_session(user_id, sid)  # type: ignore[return-value]

    def get_session(self, user_id: str, session_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
        return _session_row_to_dict(row) if row else None

    def list_sessions(self, user_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM chat_sessions WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [_session_row_to_dict(r) for r in rows]

    def update_session(
        self, user_id: str, session_id: str, **fields,
    ) -> Optional[dict]:
        existing = self.get_session(user_id, session_id)
        if not existing:
            return None
        allowed = {"title", "skill_id"}
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            sets.append(f"{k} = ?")
            vals.append(v)
        if not sets:
            return existing
        sets.append("updated_at = ?")
        vals.append(_now_iso())
        vals.extend([session_id, user_id])
        self.conn.execute(
            f"UPDATE chat_sessions SET {', '.join(sets)} WHERE id = ? AND user_id = ?", vals
        )
        self.conn.commit()
        return self.get_session(user_id, session_id)

    def touch_session(self, user_id: str, session_id: str) -> None:
        """更新 session.updated_at（用于消息追加后排序到最前）。"""
        self.conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ? AND user_id = ?",
            (_now_iso(), session_id, user_id),
        )
        self.conn.commit()

    def delete_session(self, user_id: str, session_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM chat_sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    # -------------------- message 操作 -------------------- #

    def list_messages(self, session_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
        return [_message_row_to_dict(r) for r in rows]

    def append_message(
        self,
        user_id: str,
        session_id: str,
        *,
        role: str,
        content: str,
        extra: Optional[dict] = None,
        message_id: Optional[str] = None,
    ) -> Optional[dict]:
        """追加消息并刷新 session.updated_at；session 不存在/不属于用户时返回 None。"""
        if self.get_session(user_id, session_id) is None:
            return None
        mid = message_id or _new_id()
        now = _now_iso()
        self.conn.execute(
            "INSERT OR REPLACE INTO chat_messages (id, session_id, role, content, extra_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                mid,
                session_id,
                role,
                content,
                json.dumps(extra or {}, ensure_ascii=False),
                now,
            ),
        )
        self.conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE id = ?",
            (now, session_id),
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? AND id = ?",
            (session_id, mid),
        ).fetchone()
        return _message_row_to_dict(row) if row else None


_instance: Optional[ChatSessionStore] = None


def get_chat_session_store() -> ChatSessionStore:
    """全局单例，需先调用 init_chat_session_store。"""
    if _instance is None:
        raise RuntimeError("ChatSessionStore 尚未初始化")
    return _instance


def init_chat_session_store(db_path: Optional[Path] = None) -> ChatSessionStore:
    global _instance
    _instance = ChatSessionStore(db_path)
    _instance.connect()
    return _instance
