"""
SQLite-based storage for scheduled tasks.
All methods accept user_id and filter by it for strict isolation.
"""
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    schedule TEXT NOT NULL,
    type TEXT NOT NULL,
    params_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER DEFAULT 1,
    last_run_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_user_id
ON scheduled_tasks(user_id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["params"] = json.loads(d.pop("params_json", "{}"))
    d["enabled"] = bool(d["enabled"])
    return d


class ScheduledTaskStore:
    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = str(db_path or settings.scheduled_tasks_db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self):
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.execute(_CREATE_INDEX_SQL)
        self._conn.commit()
        logger.info(f"ScheduledTaskStore connected: {self._db_path}")

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Store not connected")
        return self._conn

    def create(self, user_id: str, name: str, schedule: str, task_type: str, params: dict) -> dict:
        task_id = uuid.uuid4().hex[:12]
        now = _now_iso()
        self.conn.execute(
            "INSERT INTO scheduled_tasks (id, user_id, name, schedule, type, params_json, enabled, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (task_id, user_id, name, schedule, task_type, json.dumps(params, ensure_ascii=False), now, now),
        )
        self.conn.commit()
        return self.get(user_id, task_id)  # type: ignore

    def get(self, user_id: str, task_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM scheduled_tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id),
        ).fetchone()
        return _row_to_dict(row) if row else None

    def get_by_id(self, task_id: str) -> Optional[dict]:
        """For scheduler internal use (no user filter)."""
        row = self.conn.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def list_tasks(self, user_id: str, enabled: Optional[bool] = None) -> list[dict]:
        sql = "SELECT * FROM scheduled_tasks WHERE user_id = ?"
        params: list = [user_id]
        if enabled is not None:
            sql += " AND enabled = ?"
            params.append(int(enabled))
        sql += " ORDER BY created_at DESC"
        return [_row_to_dict(r) for r in self.conn.execute(sql, params).fetchall()]

    def list_all_enabled(self) -> list[dict]:
        """For scheduler startup: load all enabled tasks across users."""
        return [
            _row_to_dict(r) for r in
            self.conn.execute("SELECT * FROM scheduled_tasks WHERE enabled = 1").fetchall()
        ]

    def update(self, user_id: str, task_id: str, **fields) -> Optional[dict]:
        existing = self.get(user_id, task_id)
        if not existing:
            return None
        allowed = {"name", "schedule", "type", "params", "enabled"}
        sets, vals = [], []
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "params":
                sets.append("params_json = ?")
                vals.append(json.dumps(v, ensure_ascii=False))
            elif k == "enabled":
                sets.append("enabled = ?")
                vals.append(int(v))
            else:
                sets.append(f"{k} = ?")
                vals.append(v)
        if not sets:
            return existing
        sets.append("updated_at = ?")
        vals.append(_now_iso())
        vals.extend([task_id, user_id])
        self.conn.execute(
            f"UPDATE scheduled_tasks SET {', '.join(sets)} WHERE id = ? AND user_id = ?", vals
        )
        self.conn.commit()
        return self.get(user_id, task_id)

    def delete(self, user_id: str, task_id: str) -> bool:
        cur = self.conn.execute(
            "DELETE FROM scheduled_tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def update_last_run(self, task_id: str):
        self.conn.execute(
            "UPDATE scheduled_tasks SET last_run_at = ? WHERE id = ?", (_now_iso(), task_id)
        )
        self.conn.commit()
