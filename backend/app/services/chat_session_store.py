"""
SQLite persistence for projects, chat sessions, messages, and project files.

The store deliberately keeps project metadata in the same database as chat
sessions so project/session moves and activity updates can be transactional.
Every externally reachable operation is scoped by ``user_id``.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

# v1: Project/session/file schema
# v2: durable filesystem cleanup outbox (an early Project build reached local data)
# v3: cleanup jobs retain user/file/byte accounting until physical deletion
LATEST_SCHEMA_VERSION = 3
_UNSET = object()


class ProjectQuotaExceededError(ValueError):
    """A Project file mutation would exceed a configured persistent-data quota."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    """Keep the historical 12-character session/message ID format."""
    return uuid.uuid4().hex[:12]


def _new_resource_id() -> str:
    """Use the full UUID entropy for new project and project-file IDs."""
    return uuid.uuid4().hex


def _row_value(row: sqlite3.Row, key: str, default=None):
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def _session_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "title": row["title"],
        "skill_id": row["skill_id"],
        "project_id": _row_value(row, "project_id"),
        "applied_context_revision": _row_value(row, "applied_context_revision"),
        "claude_session_id": _row_value(row, "claude_session_id"),
        "opencode_session_id": _row_value(row, "opencode_session_id"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _message_row_to_dict(row: sqlite3.Row) -> dict:
    try:
        extra = json.loads(row["extra_json"] or "{}")
    except Exception:
        extra = {}
    if not isinstance(extra, dict):
        extra = {}
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "extra": extra,
        "created_at": row["created_at"],
    }


def _project_row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "description": row["description"],
        "instructions": row["instructions"],
        "context_revision": row["context_revision"],
        "archived_at": row["archived_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "last_activity_at": row["last_activity_at"],
        "session_count": int(_row_value(row, "session_count", 0) or 0),
    }


def _project_file_row_to_dict(
    row: sqlite3.Row, *, include_storage: bool = False
) -> dict:
    result = {
        "id": row["id"],
        "project_id": row["project_id"],
        "display_name": row["display_name"],
        "media_type": row["media_type"],
        "size_bytes": row["size_bytes"],
        "sha256": row["sha256"],
        "source_session_id": row["source_session_id"],
        "created_at": row["created_at"],
    }
    if include_storage:
        result["storage_name"] = row["storage_name"]
    return result


class ChatSessionStore:
    """Thread-safe SQLite store shared by synchronous FastAPI handlers.

    ``check_same_thread=False`` alone does not serialize transactions.  The
    re-entrant lock protects both reads and writes on the singleton connection,
    while ``BEGIN IMMEDIATE`` makes multi-statement mutations atomic.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = str(db_path or settings.chat_sessions_db_path)
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

    def connect(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            try:
                self._migrate_schema()
            except Exception:
                self._conn.close()
                self._conn = None
                raise
            logger.info(
                "ChatSessionStore connected: %s (schema v%s)",
                self._db_path,
                LATEST_SCHEMA_VERSION,
            )

    def close(self) -> None:
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("ChatSessionStore 尚未连接")
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

    # -------------------- schema migration -------------------- #

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone() is not None

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
        return {
            row["name"]: row
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }

    @staticmethod
    def _create_projects_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                instructions TEXT NOT NULL DEFAULT '',
                context_revision INTEGER NOT NULL DEFAULT 1,
                archived_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_activity_at TEXT NOT NULL
            )
            """
        )

    @staticmethod
    def _create_sessions_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '新建会话',
                skill_id TEXT,
                project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                applied_context_revision INTEGER,
                claude_session_id TEXT,
                opencode_session_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

    @staticmethod
    def _create_messages_table(
        conn: sqlite3.Connection, table_name: str = "chat_messages"
    ) -> None:
        conn.execute(
            f"""
            CREATE TABLE {table_name} (
                id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                extra_json TEXT NOT NULL DEFAULT '{{}}',
                created_at TEXT NOT NULL,
                PRIMARY KEY (session_id, id),
                FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
            )
            """
        )

    @staticmethod
    def _create_project_files_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS project_files (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                display_name TEXT NOT NULL,
                storage_name TEXT NOT NULL,
                media_type TEXT,
                size_bytes INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                source_session_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(project_id, storage_name),
                FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
                FOREIGN KEY(source_session_id) REFERENCES chat_sessions(id) ON DELETE SET NULL
            )
            """
        )

    @staticmethod
    def _create_storage_cleanup_jobs_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS storage_cleanup_jobs (
                id TEXT PRIMARY KEY,
                resource_type TEXT NOT NULL CHECK(resource_type IN ('project', 'file')),
                project_id TEXT NOT NULL,
                storage_name TEXT NOT NULL DEFAULT '',
                user_id TEXT NOT NULL DEFAULT '',
                file_count INTEGER NOT NULL DEFAULT 0,
                size_bytes INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT ''
            )
            """
        )

    def _normalize_messages_table(self, conn: sqlite3.Connection) -> None:
        if not self._table_exists(conn, "chat_messages"):
            self._create_messages_table(conn)
            return

        columns = self._columns(conn, "chat_messages")
        expected_core = {"id", "session_id", "role", "content", "created_at"}
        missing_core = expected_core.difference(columns)
        if missing_core:
            raise RuntimeError(
                "chat_messages 历史表缺少必要列，拒绝破坏性迁移: "
                + ", ".join(sorted(missing_core))
            )

        composite_pk = (
            int(columns["session_id"]["pk"] or 0) == 1
            and int(columns["id"]["pk"] or 0) == 2
        )
        if composite_pk and "extra_json" in columns:
            return

        logger.info(
            "迁移 chat_messages：重建为复合主键 (session_id, id)，旧 PK=(id:%s, session:%s)",
            columns["id"]["pk"],
            columns["session_id"]["pk"],
        )
        source_count = int(
            conn.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
        )
        conn.execute("DROP TABLE IF EXISTS chat_messages__new")
        self._create_messages_table(conn, "chat_messages__new")
        extra_expr = "COALESCE(extra_json, '{}')" if "extra_json" in columns else "'{}'"
        conn.execute(
            f"""
            INSERT INTO chat_messages__new
                (id, session_id, role, content, extra_json, created_at)
            SELECT id, session_id, role, content, {extra_expr}, created_at
            FROM chat_messages
            """
        )
        copied_count = int(
            conn.execute("SELECT COUNT(*) FROM chat_messages__new").fetchone()[0]
        )
        if copied_count != source_count:
            raise RuntimeError(
                "chat_messages 迁移复制计数不一致: "
                f"source={source_count}, copied={copied_count}"
            )
        conn.execute("DROP TABLE chat_messages")
        conn.execute("ALTER TABLE chat_messages__new RENAME TO chat_messages")

    @staticmethod
    def _create_indexes(conn: sqlite3.Connection) -> None:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_sessions_user "
            "ON chat_sessions(user_id, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_project "
            "ON chat_sessions(user_id, project_id, updated_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_chat_messages_session "
            "ON chat_messages(session_id, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_projects_user_activity "
            "ON projects(user_id, archived_at, last_activity_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_files_project "
            "ON project_files(project_id, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_storage_cleanup_created "
            "ON storage_cleanup_jobs(created_at)"
        )

    def _migrate_schema(self) -> None:
        """Normalize every known historical schema in one atomic transaction.

        Shape checks intentionally run even when ``user_version`` is current.
        Some deployed databases were created by an older unversioned build whose
        ``chat_messages`` table used ``id`` as the sole primary key.
        """
        current = int(self.conn.execute("PRAGMA user_version").fetchone()[0])
        if current > LATEST_SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库 schema v{current} 高于当前程序支持的 v{LATEST_SCHEMA_VERSION}"
            )

        with self._transaction() as conn:
            self._create_projects_table(conn)
            self._create_sessions_table(conn)

            session_columns = self._columns(conn, "chat_sessions")
            additions = {
                "claude_session_id": "TEXT",
                "opencode_session_id": "TEXT",
                "project_id": "TEXT REFERENCES projects(id) ON DELETE SET NULL",
                "applied_context_revision": "INTEGER",
            }
            for name, sql_type in additions.items():
                if name not in session_columns:
                    logger.info("迁移 chat_sessions：追加列 %s", name)
                    conn.execute(
                        f"ALTER TABLE chat_sessions ADD COLUMN {name} {sql_type}"
                    )

            self._normalize_messages_table(conn)
            self._create_project_files_table(conn)
            self._create_storage_cleanup_jobs_table(conn)
            cleanup_columns = self._columns(conn, "storage_cleanup_jobs")
            cleanup_additions = {
                "user_id": "TEXT NOT NULL DEFAULT ''",
                "file_count": "INTEGER NOT NULL DEFAULT 0",
                "size_bytes": "INTEGER NOT NULL DEFAULT 0",
            }
            for name, sql_type in cleanup_additions.items():
                if name not in cleanup_columns:
                    logger.info("迁移 storage_cleanup_jobs：追加列 %s", name)
                    conn.execute(
                        f"ALTER TABLE storage_cleanup_jobs ADD COLUMN {name} {sql_type}"
                    )
            self._create_indexes(conn)

            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                preview = [tuple(row) for row in violations[:10]]
                raise RuntimeError(f"数据库外键检查失败，迁移已回滚: {preview}")
            conn.execute(f"PRAGMA user_version={LATEST_SCHEMA_VERSION}")

    # -------------------- project operations -------------------- #

    def _project_row(
        self,
        conn: sqlite3.Connection,
        user_id: str,
        project_id: str,
        *,
        active_only: bool = False,
    ) -> Optional[sqlite3.Row]:
        sql = (
            "SELECT p.*, COUNT(s.id) AS session_count "
            "FROM projects p LEFT JOIN chat_sessions s "
            "ON s.project_id = p.id AND s.user_id = p.user_id "
            "WHERE p.id = ? AND p.user_id = ?"
        )
        params: list[object] = [project_id, user_id]
        if active_only:
            sql += " AND p.archived_at IS NULL"
        sql += " GROUP BY p.id"
        return conn.execute(sql, params).fetchone()

    def create_project(
        self,
        user_id: str,
        *,
        name: str,
        description: str = "",
        instructions: str = "",
        project_id: Optional[str] = None,
    ) -> dict:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("项目名称不能为空")
        pid = project_id or _new_resource_id()
        now = _now_iso()
        with self._transaction() as conn:
            conn.execute(
                """
                INSERT INTO projects
                    (id, user_id, name, description, instructions, context_revision,
                     archived_at, created_at, updated_at, last_activity_at)
                VALUES (?, ?, ?, ?, ?, 1, NULL, ?, ?, ?)
                """,
                (pid, user_id, clean_name, description or "", instructions or "", now, now, now),
            )
        return self.get_project(user_id, pid)  # type: ignore[return-value]

    def get_project(self, user_id: str, project_id: str) -> Optional[dict]:
        with self._lock:
            row = self._project_row(self.conn, user_id, project_id)
            return _project_row_to_dict(row) if row else None

    def list_projects(
        self, user_id: str, include_archived: bool = False
    ) -> list[dict]:
        sql = (
            "SELECT p.*, COUNT(s.id) AS session_count "
            "FROM projects p LEFT JOIN chat_sessions s "
            "ON s.project_id = p.id AND s.user_id = p.user_id "
            "WHERE p.user_id = ?"
        )
        if not include_archived:
            sql += " AND p.archived_at IS NULL"
        sql += " GROUP BY p.id ORDER BY p.last_activity_at DESC, p.created_at DESC"
        with self._lock:
            rows = self.conn.execute(sql, (user_id,)).fetchall()
            return [_project_row_to_dict(row) for row in rows]

    def update_project(
        self, user_id: str, project_id: str, **fields
    ) -> Optional[dict]:
        allowed = {"name", "description", "instructions", "archived_at", "archived"}
        with self._transaction() as conn:
            existing_row = self._project_row(conn, user_id, project_id)
            if not existing_row:
                return None

            sets: list[str] = []
            values: list[object] = []
            context_changed = False
            now = _now_iso()
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key == "archived":
                    key = "archived_at"
                    value = now if bool(value) else None
                if key == "name":
                    value = (value or "").strip()
                    if not value:
                        raise ValueError("项目名称不能为空")
                if key in {"description", "instructions"} and value is None:
                    value = ""
                if existing_row[key] == value:
                    continue
                sets.append(f"{key} = ?")
                values.append(value)
                if key in {"name", "description", "instructions"}:
                    context_changed = True

            if not sets:
                return _project_row_to_dict(existing_row)
            if context_changed:
                sets.append("context_revision = context_revision + 1")
            sets.append("updated_at = ?")
            values.append(now)
            values.extend([project_id, user_id])
            conn.execute(
                f"UPDATE projects SET {', '.join(sets)} WHERE id = ? AND user_id = ?",
                values,
            )
        return self.get_project(user_id, project_id)

    def delete_project(self, user_id: str, project_id: str) -> bool:
        """Delete project metadata/files while preserving all child sessions.

        Sessions are atomically unassigned and provider-native IDs are cleared
        so a subsequent turn cannot resume with stale project context.
        """
        with self._transaction() as conn:
            if not self._project_row(conn, user_id, project_id):
                return False
            usage = conn.execute(
                """
                SELECT COUNT(*) AS file_count,
                       COALESCE(SUM(size_bytes), 0) AS size_bytes
                FROM project_files WHERE project_id = ?
                """,
                (project_id,),
            ).fetchone()
            conn.execute(
                """
                UPDATE chat_sessions
                SET project_id = NULL,
                    applied_context_revision = NULL,
                    claude_session_id = NULL,
                    opencode_session_id = NULL,
                    updated_at = ?
                WHERE user_id = ? AND project_id = ?
                """,
                (_now_iso(), user_id, project_id),
            )
            deleted = conn.execute(
                "DELETE FROM projects WHERE id = ? AND user_id = ?",
                (project_id, user_id),
            )
            if deleted.rowcount > 0:
                self._enqueue_storage_cleanup(
                    conn,
                    resource_type="project",
                    project_id=project_id,
                    user_id=user_id,
                    file_count=int(usage["file_count"]),
                    size_bytes=int(usage["size_bytes"]),
                )
            return deleted.rowcount > 0

    # -------------------- project file metadata -------------------- #

    def list_project_files(
        self, user_id: str, project_id: str, *, include_storage: bool = False
    ) -> list[dict]:
        with self._lock:
            if not self._project_row(self.conn, user_id, project_id):
                return []
            rows = self.conn.execute(
                "SELECT * FROM project_files WHERE project_id = ? ORDER BY created_at ASC",
                (project_id,),
            ).fetchall()
            return [
                _project_file_row_to_dict(row, include_storage=include_storage)
                for row in rows
            ]

    def get_project_file(
        self,
        user_id: str,
        project_id: str,
        file_id: str,
        *,
        include_storage: bool = False,
    ) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT f.* FROM project_files f
                JOIN projects p ON p.id = f.project_id
                WHERE f.id = ? AND f.project_id = ? AND p.user_id = ?
                """,
                (file_id, project_id, user_id),
            ).fetchone()
            return (
                _project_file_row_to_dict(row, include_storage=include_storage)
                if row
                else None
            )

    @staticmethod
    def _project_file_usage(
        conn: sqlite3.Connection, user_id: str, project_id: str
    ) -> dict[str, int]:
        project_usage = conn.execute(
            """
            SELECT COUNT(*) AS file_count, COALESCE(SUM(size_bytes), 0) AS total_bytes
            FROM project_files WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        user_usage = conn.execute(
            """
            SELECT COUNT(*) AS file_count, COALESCE(SUM(f.size_bytes), 0) AS total_bytes
            FROM project_files f
            JOIN projects p ON p.id = f.project_id
            WHERE p.user_id = ?
            """,
            (user_id,),
        ).fetchone()
        project_pending = conn.execute(
            """
            SELECT COALESCE(SUM(file_count), 0) AS file_count,
                   COALESCE(SUM(size_bytes), 0) AS total_bytes
            FROM storage_cleanup_jobs WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        user_pending = conn.execute(
            """
            SELECT COALESCE(SUM(file_count), 0) AS file_count,
                   COALESCE(SUM(size_bytes), 0) AS total_bytes
            FROM storage_cleanup_jobs WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        return {
            "project_file_count": int(project_usage["file_count"])
            + int(project_pending["file_count"]),
            "project_total_bytes": int(project_usage["total_bytes"])
            + int(project_pending["total_bytes"]),
            "user_file_count": int(user_usage["file_count"])
            + int(user_pending["file_count"]),
            "user_total_bytes": int(user_usage["total_bytes"])
            + int(user_pending["total_bytes"]),
        }

    def get_project_file_capacity(
        self, user_id: str, project_id: str
    ) -> Optional[dict[str, int]]:
        """Return remaining logical capacity, including pending physical cleanup."""
        with self._lock:
            if not self._project_row(
                self.conn, user_id, project_id, active_only=True
            ):
                return None
            usage = self._project_file_usage(self.conn, user_id, project_id)
            project_remaining_files = (
                settings.EIDO_PROJECT_MAX_FILES - usage["project_file_count"]
            )
            user_remaining_files = (
                settings.EIDO_USER_PROJECT_MAX_FILES - usage["user_file_count"]
            )
            project_remaining_bytes = (
                settings.EIDO_PROJECT_MAX_BYTES - usage["project_total_bytes"]
            )
            user_remaining_bytes = (
                settings.EIDO_USER_PROJECT_MAX_BYTES - usage["user_total_bytes"]
            )
            return {
                "project_remaining_files": project_remaining_files,
                "user_remaining_files": user_remaining_files,
                "project_remaining_bytes": project_remaining_bytes,
                "user_remaining_bytes": user_remaining_bytes,
                "remaining_files": min(project_remaining_files, user_remaining_files),
                "remaining_bytes": min(project_remaining_bytes, user_remaining_bytes),
            }

    def add_project_file(
        self,
        user_id: str,
        project_id: str,
        *,
        display_name: str,
        storage_name: str,
        media_type: Optional[str],
        size_bytes: int,
        sha256: str,
        source_session_id: Optional[str] = None,
        file_id: Optional[str] = None,
    ) -> dict:
        if not (display_name or "").strip():
            raise ValueError("文件名不能为空")
        if not (storage_name or "").strip():
            raise ValueError("存储文件名不能为空")
        if int(size_bytes) < 0:
            raise ValueError("文件大小不能为负数")
        fid = file_id or _new_resource_id()
        now = _now_iso()
        result: Optional[dict] = None
        with self._transaction() as conn:
            if not self._project_row(conn, user_id, project_id, active_only=True):
                raise ValueError("项目不存在、不属于当前用户或已归档")
            if source_session_id:
                source = conn.execute(
                    """
                    SELECT 1 FROM chat_sessions
                    WHERE id = ? AND user_id = ? AND project_id = ?
                    """,
                    (source_session_id, user_id, project_id),
                ).fetchone()
                if not source:
                    raise ValueError(
                        "来源会话不存在、不属于当前用户或当前不在目标项目中"
                    )
            usage = self._project_file_usage(conn, user_id, project_id)
            if usage["project_file_count"] >= settings.EIDO_PROJECT_MAX_FILES:
                raise ProjectQuotaExceededError("项目共享资料数量已达上限")
            if (
                usage["project_total_bytes"] + int(size_bytes)
                > settings.EIDO_PROJECT_MAX_BYTES
            ):
                raise ProjectQuotaExceededError("项目共享资料总容量已达上限")
            if usage["user_file_count"] >= settings.EIDO_USER_PROJECT_MAX_FILES:
                raise ProjectQuotaExceededError("当前用户的项目资料数量已达上限")
            if (
                usage["user_total_bytes"] + int(size_bytes)
                > settings.EIDO_USER_PROJECT_MAX_BYTES
            ):
                raise ProjectQuotaExceededError("当前用户的项目资料总容量已达上限")
            conn.execute(
                """
                INSERT INTO project_files
                    (id, project_id, display_name, storage_name, media_type,
                     size_bytes, sha256, source_session_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    fid,
                    project_id,
                    display_name.strip(),
                    storage_name.strip(),
                    media_type,
                    int(size_bytes),
                    sha256,
                    source_session_id,
                    now,
                ),
            )
            conn.execute(
                """
                UPDATE projects
                SET context_revision = context_revision + 1,
                    updated_at = ?, last_activity_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (now, now, project_id, user_id),
            )
            row = conn.execute(
                "SELECT * FROM project_files WHERE id = ? AND project_id = ?",
                (fid, project_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("项目文件元数据写入后无法读取")
            result = _project_file_row_to_dict(row)
            revision_row = conn.execute(
                "SELECT context_revision FROM projects WHERE id = ? AND user_id = ?",
                (project_id, user_id),
            ).fetchone()
            if revision_row is None:
                raise RuntimeError("项目文件写入后无法读取上下文版本")
            result["context_revision"] = int(revision_row["context_revision"])
        if result is None:
            raise RuntimeError("项目文件元数据事务未生成结果")
        return result

    def delete_project_file(
        self, user_id: str, project_id: str, file_id: str
    ) -> bool:
        now = _now_iso()
        with self._transaction() as conn:
            owned = conn.execute(
                """
                SELECT f.storage_name, f.size_bytes FROM project_files f
                JOIN projects p ON p.id = f.project_id
                WHERE f.id = ? AND f.project_id = ? AND p.user_id = ?
                """,
                (file_id, project_id, user_id),
            ).fetchone()
            if not owned:
                return False
            conn.execute(
                "DELETE FROM project_files WHERE id = ? AND project_id = ?",
                (file_id, project_id),
            )
            self._enqueue_storage_cleanup(
                conn,
                resource_type="file",
                project_id=project_id,
                storage_name=owned["storage_name"],
                user_id=user_id,
                file_count=1,
                size_bytes=int(owned["size_bytes"]),
            )
            conn.execute(
                """
                UPDATE projects
                SET context_revision = context_revision + 1, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (now, project_id, user_id),
            )
            return True

    def get_project_context_for_session(
        self, user_id: str, session_id: str
    ) -> Optional[dict]:
        """Return a server-derived project context; never accepts project_id."""
        with self._lock:
            row = self.conn.execute(
                """
                SELECT p.*, s.applied_context_revision
                FROM chat_sessions s
                JOIN projects p ON p.id = s.project_id AND p.user_id = s.user_id
                WHERE s.id = ? AND s.user_id = ?
                """,
                (session_id, user_id),
            ).fetchone()
            if not row:
                return None
            files = self.conn.execute(
                """
                SELECT * FROM project_files
                WHERE project_id = ? ORDER BY created_at ASC LIMIT ?
                """,
                (row["id"], settings.EIDO_PROJECT_MAX_FILES),
            ).fetchall()
            return {
                "id": row["id"],
                "name": row["name"],
                "description": row["description"],
                "instructions": row["instructions"],
                "context_revision": row["context_revision"],
                "applied_context_revision": row["applied_context_revision"],
                "archived_at": row["archived_at"],
                "files": [
                    _project_file_row_to_dict(file_row, include_storage=True)
                    for file_row in files
                ],
            }

    # -------------------- retryable filesystem cleanup -------------------- #

    @staticmethod
    def _cleanup_job_id(
        resource_type: str, project_id: str, storage_name: str = ""
    ) -> str:
        return f"{resource_type}:{project_id}:{storage_name}"

    @classmethod
    def _enqueue_storage_cleanup(
        cls,
        conn: sqlite3.Connection,
        *,
        resource_type: str,
        project_id: str,
        storage_name: str = "",
        user_id: str = "",
        file_count: int = 0,
        size_bytes: int = 0,
    ) -> str:
        if resource_type not in {"project", "file"}:
            raise ValueError("非法清理任务类型")
        job_id = cls._cleanup_job_id(resource_type, project_id, storage_name)
        conn.execute(
            """
            INSERT INTO storage_cleanup_jobs
                (id, resource_type, project_id, storage_name, user_id,
                 file_count, size_bytes, created_at, attempts, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, '')
            ON CONFLICT(id) DO UPDATE SET
                last_error = '',
                user_id = CASE
                    WHEN storage_cleanup_jobs.user_id = ''
                         AND excluded.user_id != ''
                    THEN excluded.user_id
                    ELSE storage_cleanup_jobs.user_id
                END,
                file_count = CASE
                    WHEN storage_cleanup_jobs.file_count = 0
                         AND excluded.file_count > 0
                    THEN excluded.file_count
                    ELSE storage_cleanup_jobs.file_count
                END,
                size_bytes = CASE
                    WHEN storage_cleanup_jobs.size_bytes = 0
                         AND excluded.size_bytes > 0
                    THEN excluded.size_bytes
                    ELSE storage_cleanup_jobs.size_bytes
                END
            """,
            (
                job_id,
                resource_type,
                project_id,
                storage_name,
                user_id,
                max(0, int(file_count)),
                max(0, int(size_bytes)),
                _now_iso(),
            ),
        )
        return job_id

    def enqueue_storage_cleanup(
        self,
        *,
        resource_type: str,
        project_id: str,
        storage_name: str = "",
        user_id: str = "",
        file_count: int = 0,
        size_bytes: int = 0,
    ) -> str:
        with self._transaction() as conn:
            return self._enqueue_storage_cleanup(
                conn,
                resource_type=resource_type,
                project_id=project_id,
                storage_name=storage_name,
                user_id=user_id,
                file_count=file_count,
                size_bytes=size_bytes,
            )

    def list_storage_cleanup_jobs(self, *, limit: int = 1000) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT * FROM storage_cleanup_jobs
                ORDER BY attempts ASC, created_at ASC LIMIT ?
                """,
                (max(1, int(limit)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def complete_storage_cleanup(
        self, *, resource_type: str, project_id: str, storage_name: str = ""
    ) -> bool:
        job_id = self._cleanup_job_id(resource_type, project_id, storage_name)
        with self._transaction() as conn:
            deleted = conn.execute(
                "DELETE FROM storage_cleanup_jobs WHERE id = ?", (job_id,)
            )
            return deleted.rowcount > 0

    def complete_project_storage_cleanup(self, project_id: str) -> int:
        """Clear every job covered by successful removal of a whole Project tree."""
        with self._transaction() as conn:
            deleted = conn.execute(
                "DELETE FROM storage_cleanup_jobs WHERE project_id = ?",
                (project_id,),
            )
            return deleted.rowcount

    def record_storage_cleanup_failure(self, job_id: str, error: str) -> None:
        with self._transaction() as conn:
            conn.execute(
                """
                UPDATE storage_cleanup_jobs
                SET attempts = attempts + 1, last_error = ? WHERE id = ?
                """,
                ((error or "")[:1000], job_id),
            )

    def project_resource_exists(self, project_id: str) -> bool:
        with self._lock:
            return self.conn.execute(
                "SELECT 1 FROM projects WHERE id = ?", (project_id,)
            ).fetchone() is not None

    def project_file_resource_exists(
        self, project_id: str, storage_name: str
    ) -> bool:
        with self._lock:
            return self.conn.execute(
                """
                SELECT 1 FROM project_files
                WHERE project_id = ? AND storage_name = ?
                """,
                (project_id, storage_name),
            ).fetchone() is not None

    def project_storage_index(self) -> tuple[dict[str, str], set[tuple[str, str]]]:
        """Return the authoritative Project/file keys for startup reconciliation."""
        with self._lock:
            projects = {
                row["id"]: row["user_id"]
                for row in self.conn.execute(
                    "SELECT id, user_id FROM projects"
                ).fetchall()
            }
            files = {
                (row["project_id"], row["storage_name"])
                for row in self.conn.execute(
                    "SELECT project_id, storage_name FROM project_files"
                ).fetchall()
            }
            return projects, files

    def mark_project_context_applied(
        self, user_id: str, session_id: str, context_revision: int
    ) -> bool:
        with self._transaction() as conn:
            updated = conn.execute(
                """
                UPDATE chat_sessions SET applied_context_revision = ?
                WHERE id = ? AND user_id = ?
                """,
                (int(context_revision), session_id, user_id),
            )
            return updated.rowcount > 0

    def prepare_project_context(
        self,
        user_id: str,
        session_id: str,
        project_id: str,
        context_revision: int,
    ) -> Optional[bool]:
        """Atomically bind a session to the exact Project context snapshot.

        ``True`` means the revision changed and provider-native session IDs were
        invalidated. ``False`` means it was already current. ``None`` means the
        session moved or the Project changed while the request was being prepared.
        """
        revision = int(context_revision)
        with self._transaction() as conn:
            row = conn.execute(
                """
                SELECT s.applied_context_revision, p.context_revision
                FROM chat_sessions s
                JOIN projects p ON p.id = s.project_id AND p.user_id = s.user_id
                WHERE s.id = ? AND s.user_id = ? AND s.project_id = ?
                """,
                (session_id, user_id, project_id),
            ).fetchone()
            if not row or int(row["context_revision"]) != revision:
                return None
            if row["applied_context_revision"] == revision:
                return False
            updated = conn.execute(
                """
                UPDATE chat_sessions
                SET applied_context_revision = ?,
                    claude_session_id = NULL,
                    opencode_session_id = NULL
                WHERE id = ? AND user_id = ? AND project_id = ?
                """,
                (revision, session_id, user_id, project_id),
            )
            return updated.rowcount > 0

    # -------------------- session operations -------------------- #

    def create_session(
        self,
        user_id: str,
        *,
        title: str = "新建会话",
        skill_id: Optional[str] = None,
        project_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        sid = session_id or _new_id()
        now = _now_iso()
        with self._transaction() as conn:
            if project_id and not self._project_row(
                conn, user_id, project_id, active_only=True
            ):
                raise ValueError("项目不存在、不属于当前用户或已归档")
            conn.execute(
                """
                INSERT INTO chat_sessions
                    (id, user_id, title, skill_id, project_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (sid, user_id, title or "新建会话", skill_id, project_id, now, now),
            )
            if project_id:
                conn.execute(
                    """
                    UPDATE projects SET last_activity_at = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (now, now, project_id, user_id),
                )
        return self.get_session(user_id, sid)  # type: ignore[return-value]

    def get_session(self, user_id: str, session_id: str) -> Optional[dict]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
            return _session_row_to_dict(row) if row else None

    def list_sessions(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        unassigned: bool = False,
    ) -> list[dict]:
        if project_id is not None and unassigned:
            raise ValueError("project_id 与 unassigned 不能同时使用")
        sql = "SELECT * FROM chat_sessions WHERE user_id = ?"
        params: list[object] = [user_id]
        with self._lock:
            if project_id is not None:
                if not self._project_row(self.conn, user_id, project_id):
                    return []
                sql += " AND project_id = ?"
                params.append(project_id)
            elif unassigned:
                sql += " AND project_id IS NULL"
            sql += " ORDER BY updated_at DESC"
            rows = self.conn.execute(sql, params).fetchall()
            return [_session_row_to_dict(row) for row in rows]

    def search_navigation(
        self, user_id: str, query: str, *, limit: int = 20
    ) -> dict[str, list[dict]]:
        """Search project metadata plus session titles and persisted message text."""
        normalized = " ".join((query or "").strip().split())
        if not normalized:
            return {"projects": [], "sessions": []}
        escaped = normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        bounded = max(1, min(int(limit), 50))
        with self._lock:
            projects = self.conn.execute(
                """
                SELECT p.*, COUNT(DISTINCT s.id) AS session_count
                FROM projects p
                LEFT JOIN chat_sessions s
                  ON s.project_id = p.id AND s.user_id = p.user_id
                WHERE p.user_id = ? AND (
                    p.name LIKE ? ESCAPE '\\' COLLATE NOCASE OR
                    p.description LIKE ? ESCAPE '\\' COLLATE NOCASE OR
                    p.instructions LIKE ? ESCAPE '\\' COLLATE NOCASE
                )
                GROUP BY p.id
                ORDER BY p.last_activity_at DESC
                LIMIT ?
                """,
                (user_id, pattern, pattern, pattern, bounded),
            ).fetchall()
            sessions = self.conn.execute(
                """
                SELECT s.*,
                       CASE WHEN s.title LIKE ? ESCAPE '\\' COLLATE NOCASE
                            THEN '' ELSE COALESCE((
                         SELECT substr(m.content, 1, 160)
                         FROM chat_messages m
                         WHERE m.session_id = s.id
                           AND m.content LIKE ? ESCAPE '\\' COLLATE NOCASE
                         ORDER BY m.created_at DESC LIMIT 1
                       ), '') END AS match_snippet
                FROM chat_sessions s
                WHERE s.user_id = ? AND (
                    s.title LIKE ? ESCAPE '\\' COLLATE NOCASE OR EXISTS (
                        SELECT 1 FROM chat_messages m
                        WHERE m.session_id = s.id
                          AND m.content LIKE ? ESCAPE '\\' COLLATE NOCASE
                    )
                )
                ORDER BY s.updated_at DESC
                LIMIT ?
                """,
                (pattern, pattern, user_id, pattern, pattern, bounded),
            ).fetchall()
        session_results = []
        for row in sessions:
            item = _session_row_to_dict(row)
            item["match_snippet"] = row["match_snippet"]
            session_results.append(item)
        return {
            "projects": [_project_row_to_dict(row) for row in projects],
            "sessions": session_results,
        }

    def update_session(
        self, user_id: str, session_id: str, **fields
    ) -> Optional[dict]:
        allowed = {"title", "skill_id", "project_id"}
        now = _now_iso()
        with self._transaction() as conn:
            existing = conn.execute(
                "SELECT * FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
            if not existing:
                return None

            sets: list[str] = []
            values: list[object] = []
            project_changed = False
            new_project_id = existing["project_id"]
            for key, value in fields.items():
                if key not in allowed:
                    continue
                if key == "project_id":
                    if value is not None and not self._project_row(
                        conn, user_id, value, active_only=True
                    ):
                        raise ValueError("项目不存在、不属于当前用户或已归档")
                    if value == existing["project_id"]:
                        continue
                    new_project_id = value
                    project_changed = True
                if key == "title" and value is None:
                    raise ValueError("会话标题不能为空")
                sets.append(f"{key} = ?")
                values.append(value)

            if not sets:
                return _session_row_to_dict(existing)
            if project_changed:
                sets.extend(
                    [
                        "applied_context_revision = NULL",
                        "claude_session_id = NULL",
                        "opencode_session_id = NULL",
                    ]
                )
            sets.append("updated_at = ?")
            values.append(now)
            values.extend([session_id, user_id])
            conn.execute(
                f"UPDATE chat_sessions SET {', '.join(sets)} "
                "WHERE id = ? AND user_id = ?",
                values,
            )
            if project_changed and new_project_id:
                conn.execute(
                    """
                    UPDATE projects SET last_activity_at = ?, updated_at = ?
                    WHERE id = ? AND user_id = ?
                    """,
                    (now, now, new_project_id, user_id),
                )
        return self.get_session(user_id, session_id)

    def touch_session(self, user_id: str, session_id: str) -> None:
        now = _now_iso()
        with self._transaction() as conn:
            row = conn.execute(
                "SELECT project_id FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
            if not row:
                return
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now, session_id, user_id),
            )
            if row["project_id"]:
                conn.execute(
                    "UPDATE projects SET last_activity_at = ? WHERE id = ? AND user_id = ?",
                    (now, row["project_id"], user_id),
                )

    def get_claude_session_id(
        self,
        user_id: str,
        session_id: str,
        *,
        expected_project_id: object = _UNSET,
        expected_context_revision: object = _UNSET,
    ) -> Optional[str]:
        with self._lock:
            where, values = self._provider_session_guard(
                session_id,
                user_id,
                expected_project_id=expected_project_id,
                expected_context_revision=expected_context_revision,
            )
            row = self.conn.execute(
                f"SELECT claude_session_id FROM chat_sessions WHERE {where}",
                values,
            ).fetchone()
            return row["claude_session_id"] or None if row else None

    def set_claude_session_id(
        self,
        user_id: str,
        session_id: str,
        claude_sid: Optional[str],
        *,
        expected_project_id: object = _UNSET,
        expected_context_revision: object = _UNSET,
    ) -> bool:
        with self._transaction() as conn:
            where, values = self._provider_session_guard(
                session_id,
                user_id,
                expected_project_id=expected_project_id,
                expected_context_revision=expected_context_revision,
            )
            cur = conn.execute(
                f"UPDATE chat_sessions SET claude_session_id = ?, updated_at = ? WHERE {where}",
                (claude_sid, _now_iso(), *values),
            )
            return cur.rowcount > 0

    def get_opencode_session_id(
        self,
        user_id: str,
        session_id: str,
        *,
        expected_project_id: object = _UNSET,
        expected_context_revision: object = _UNSET,
    ) -> Optional[str]:
        with self._lock:
            where, values = self._provider_session_guard(
                session_id,
                user_id,
                expected_project_id=expected_project_id,
                expected_context_revision=expected_context_revision,
            )
            row = self.conn.execute(
                f"SELECT opencode_session_id FROM chat_sessions WHERE {where}",
                values,
            ).fetchone()
            return row["opencode_session_id"] or None if row else None

    def set_opencode_session_id(
        self,
        user_id: str,
        session_id: str,
        opencode_sid: Optional[str],
        *,
        expected_project_id: object = _UNSET,
        expected_context_revision: object = _UNSET,
    ) -> bool:
        with self._transaction() as conn:
            where, values = self._provider_session_guard(
                session_id,
                user_id,
                expected_project_id=expected_project_id,
                expected_context_revision=expected_context_revision,
            )
            cur = conn.execute(
                f"UPDATE chat_sessions SET opencode_session_id = ?, updated_at = ? WHERE {where}",
                (opencode_sid, _now_iso(), *values),
            )
            return cur.rowcount > 0

    @staticmethod
    def _provider_session_guard(
        session_id: str,
        user_id: str,
        *,
        expected_project_id: object,
        expected_context_revision: object,
    ) -> tuple[str, list[object]]:
        where = "id = ? AND user_id = ?"
        values: list[object] = [session_id, user_id]
        if expected_project_id is not _UNSET:
            if expected_project_id is None:
                where += " AND project_id IS NULL"
            else:
                where += " AND project_id = ?"
                values.append(expected_project_id)
        if expected_context_revision is not _UNSET:
            if expected_context_revision is None:
                where += " AND applied_context_revision IS NULL"
            else:
                where += " AND applied_context_revision = ?"
                values.append(expected_context_revision)
                if expected_project_id is not _UNSET and expected_project_id is not None:
                    # ``applied_context_revision`` records the snapshot used by
                    # the session, but the Project can advance while that request
                    # is still running. Refuse both reads and late writes of a
                    # provider-native SID once the authoritative Project revision
                    # no longer matches the request snapshot.
                    where += (
                        " AND EXISTS ("
                        "SELECT 1 FROM projects p "
                        "WHERE p.id = chat_sessions.project_id "
                        "AND p.user_id = chat_sessions.user_id "
                        "AND p.context_revision = ?"
                        ")"
                    )
                    values.append(expected_context_revision)
        return where, values

    def delete_session(self, user_id: str, session_id: str) -> bool:
        with self._transaction() as conn:
            cur = conn.execute(
                "DELETE FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            )
            return cur.rowcount > 0

    # -------------------- message operations -------------------- #

    def list_messages(
        self, session_id: str, *, user_id: Optional[str] = None, limit: Optional[int] = None
    ) -> list[dict]:
        params: list[object]
        if user_id is None:
            sql = "SELECT m.* FROM chat_messages m WHERE m.session_id = ?"
            params = [session_id]
        else:
            sql = (
                "SELECT m.* FROM chat_messages m JOIN chat_sessions s ON s.id = m.session_id "
                "WHERE m.session_id = ? AND s.user_id = ?"
            )
            params = [session_id, user_id]
        sql += " ORDER BY m.created_at ASC"
        if limit is not None:
            # Preserve chronological order while selecting the newest bounded history.
            sql = f"SELECT * FROM ({sql.replace(' ORDER BY m.created_at ASC', ' ORDER BY m.created_at DESC')} LIMIT ?) ORDER BY created_at ASC"
            params.append(max(1, int(limit)))
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
            return [_message_row_to_dict(row) for row in rows]

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
        mid = message_id or _new_id()
        now = _now_iso()
        with self._transaction() as conn:
            session = conn.execute(
                "SELECT project_id FROM chat_sessions WHERE id = ? AND user_id = ?",
                (session_id, user_id),
            ).fetchone()
            if not session:
                return None
            conn.execute(
                """
                INSERT INTO chat_messages
                    (id, session_id, role, content, extra_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, id) DO UPDATE SET
                    role = excluded.role,
                    content = excluded.content,
                    extra_json = excluded.extra_json
                """,
                (
                    mid,
                    session_id,
                    role,
                    content,
                    json.dumps(extra or {}, ensure_ascii=False),
                    now,
                ),
            )
            conn.execute(
                "UPDATE chat_sessions SET updated_at = ? WHERE id = ? AND user_id = ?",
                (now, session_id, user_id),
            )
            if session["project_id"]:
                conn.execute(
                    "UPDATE projects SET last_activity_at = ? WHERE id = ? AND user_id = ?",
                    (now, session["project_id"], user_id),
                )
            row = conn.execute(
                "SELECT * FROM chat_messages WHERE session_id = ? AND id = ?",
                (session_id, mid),
            ).fetchone()
            return _message_row_to_dict(row) if row else None


_instance: Optional[ChatSessionStore] = None


def get_chat_session_store() -> ChatSessionStore:
    if _instance is None:
        raise RuntimeError("ChatSessionStore 尚未初始化")
    return _instance


def init_chat_session_store(db_path: Optional[Path] = None) -> ChatSessionStore:
    global _instance
    if _instance is not None:
        _instance.close()
    _instance = ChatSessionStore(db_path)
    _instance.connect()
    return _instance
