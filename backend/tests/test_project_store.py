"""Project store and SQLite migration contract tests.

Every test uses a temporary database. Never point these tests at the repository's
``.eido/chat_sessions.db`` or a deployed ``/data`` volume.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.chat_session_store import (
    ChatSessionStore,
    LATEST_SCHEMA_VERSION,
    ProjectQuotaExceededError,
)


def _table_columns(conn: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return {
        row["name"]: row
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _message_primary_key(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        name: int(row["pk"])
        for name, row in _table_columns(conn, "chat_messages").items()
        if row["pk"]
    }


def _create_id_only_legacy_database(path: Path) -> None:
    """Reproduce the oldest schema observed in an existing Eido data directory."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE chat_sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '新建会话',
            skill_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_chat_sessions_user
            ON chat_sessions(user_id, updated_at DESC);
        CREATE TABLE chat_messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            extra_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        );
        CREATE INDEX idx_chat_messages_session
            ON chat_messages(session_id, created_at);
        """
    )
    sessions = [
        (
            "legacy-s1",
            "u1",
            "legacy one",
            None,
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
        ),
        (
            "legacy-s2",
            "u1",
            "legacy two",
            None,
            "2026-01-02T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
        ),
    ]
    conn.executemany(
        "INSERT INTO chat_sessions"
        " (id, user_id, title, skill_id, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        sessions,
    )
    conn.executemany(
        "INSERT INTO chat_messages"
        " (id, session_id, role, content, extra_json, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("legacy-m1", "legacy-s1", "user", "first", "{}", "2026-01-01T00:00:01+00:00"),
            ("legacy-m2", "legacy-s2", "assistant", "second", "{}", "2026-01-02T00:00:01+00:00"),
        ],
    )
    conn.commit()
    conn.close()


def _create_composite_key_history_database(path: Path, provider_columns: tuple[str, ...]) -> None:
    """Create each committed pre-Project chat_sessions shape."""
    provider_sql = "".join(f", {name} TEXT" for name in provider_columns)
    provider_names = ", ".join(provider_columns)
    provider_placeholders = ", ".join("?" for _ in provider_columns)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE chat_sessions ("
        "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL, skill_id TEXT, "
        "created_at TEXT NOT NULL, updated_at TEXT NOT NULL"
        f"{provider_sql})"
    )
    conn.execute(
        "CREATE TABLE chat_messages ("
        "id TEXT NOT NULL, session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, "
        "extra_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL, "
        "PRIMARY KEY (session_id, id), "
        "FOREIGN KEY(session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE)"
    )
    values: list[object] = [
        "history-s1",
        "u1",
        "history",
        None,
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:00:00+00:00",
    ]
    values.extend(f"{column}-value" for column in provider_columns)
    suffix = f", {provider_names}" if provider_names else ""
    placeholders = f", {provider_placeholders}" if provider_placeholders else ""
    conn.execute(
        "INSERT INTO chat_sessions "
        f"(id, user_id, title, skill_id, created_at, updated_at{suffix}) "
        f"VALUES (?, ?, ?, ?, ?, ?{placeholders})",
        values,
    )
    conn.execute(
        "INSERT INTO chat_messages VALUES (?, ?, ?, ?, ?, ?)",
        ("history-m1", "history-s1", "user", "preserve", "{}", "2026-01-01T00:00:01+00:00"),
    )
    conn.commit()
    conn.close()


def _create_v2_cleanup_database(path: Path) -> None:
    """Reproduce the early cleanup-outbox schema observed in a real data root."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE storage_cleanup_jobs (
            id TEXT PRIMARY KEY,
            resource_type TEXT NOT NULL CHECK(resource_type IN ('project', 'file')),
            project_id TEXT NOT NULL,
            storage_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO storage_cleanup_jobs
            (id, resource_type, project_id, storage_name, created_at, attempts, last_error)
        VALUES
            ('file:p1:old.md', 'file', 'p1', 'old.md',
             '2026-07-23T00:00:00+00:00', 2, 'retry me');
        PRAGMA user_version=2;
        """
    )
    conn.close()


@pytest.fixture
def store(tmp_path: Path):
    value = ChatSessionStore(tmp_path / "chat_sessions.db")
    value.connect()
    try:
        yield value
    finally:
        value.close()


def test_fresh_database_has_versioned_project_schema(store: ChatSessionStore):
    conn = store.conn
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    assert {
        "projects",
        "project_files",
        "chat_sessions",
        "chat_messages",
        "storage_cleanup_jobs",
    } <= tables

    assert {
        "id",
        "user_id",
        "name",
        "description",
        "instructions",
        "context_revision",
        "archived_at",
        "created_at",
        "updated_at",
        "last_activity_at",
    } <= set(_table_columns(conn, "projects"))
    assert {"project_id", "applied_context_revision"} <= set(
        _table_columns(conn, "chat_sessions")
    )
    assert _message_primary_key(conn) == {"session_id": 1, "id": 2}
    assert {
        "id",
        "resource_type",
        "project_id",
        "storage_name",
        "user_id",
        "file_count",
        "size_bytes",
        "created_at",
        "attempts",
        "last_error",
    } <= set(_table_columns(conn, "storage_cleanup_jobs"))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_SCHEMA_VERSION
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migrates_observed_v2_cleanup_outbox_to_v3_without_data_loss(
    tmp_path: Path,
):
    db_path = tmp_path / "schema-v2.db"
    _create_v2_cleanup_database(db_path)

    value = ChatSessionStore(db_path)
    value.connect()
    try:
        assert value.conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert {"user_id", "file_count", "size_bytes"} <= set(
            _table_columns(value.conn, "storage_cleanup_jobs")
        )
        assert value.list_storage_cleanup_jobs() == [
            {
                "id": "file:p1:old.md",
                "resource_type": "file",
                "project_id": "p1",
                "storage_name": "old.md",
                "created_at": "2026-07-23T00:00:00+00:00",
                "attempts": 2,
                "last_error": "retry me",
                "user_id": "",
                "file_count": 0,
                "size_bytes": 0,
            }
        ]
        assert value.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        value.close()


def test_v2_migration_failure_rolls_back_columns_and_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    db_path = tmp_path / "schema-v2-rollback.db"
    _create_v2_cleanup_database(db_path)

    def fail_after_column_additions(_conn: sqlite3.Connection) -> None:
        raise RuntimeError("injected migration failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            ChatSessionStore,
            "_create_indexes",
            staticmethod(fail_after_column_additions),
        )
        value = ChatSessionStore(db_path)
        with pytest.raises(RuntimeError, match="injected migration failure"):
            value.connect()

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        assert {"user_id", "file_count", "size_bytes"}.isdisjoint(
            _table_columns(conn, "storage_cleanup_jobs")
        )
        assert [
            tuple(row)
            for row in conn.execute(
                "SELECT id, attempts, last_error FROM storage_cleanup_jobs"
            ).fetchall()
        ] == [("file:p1:old.md", 2, "retry me")]
    finally:
        conn.close()

    recovered = ChatSessionStore(db_path)
    recovered.connect()
    try:
        assert recovered.conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert {"user_id", "file_count", "size_bytes"} <= set(
            _table_columns(recovered.conn, "storage_cleanup_jobs")
        )
    finally:
        recovered.close()


def test_rejects_unknown_future_schema_without_modifying_it(tmp_path: Path):
    db_path = tmp_path / "future.db"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA user_version=4")
    conn.close()

    value = ChatSessionStore(db_path)
    with pytest.raises(
        RuntimeError,
        match="数据库 schema v4 高于当前程序支持的 v3",
    ):
        value.connect()

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall() == []
    finally:
        conn.close()


def test_migrates_id_only_message_primary_key_without_data_loss(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    _create_id_only_legacy_database(db_path)

    value = ChatSessionStore(db_path)
    value.connect()
    try:
        assert _message_primary_key(value.conn) == {"session_id": 1, "id": 2}
        assert {"project_id", "applied_context_revision"} <= set(
            _table_columns(value.conn, "chat_sessions")
        )
        assert len(value.list_messages("legacy-s1")) == 1
        assert len(value.list_messages("legacy-s2")) == 1

        # The repaired composite key permits the same client message ID in two sessions.
        assert value.append_message(
            "u1", "legacy-s1", role="user", content="one", message_id="same-id"
        )
        assert value.append_message(
            "u1", "legacy-s2", role="user", content="two", message_id="same-id"
        )
        assert [
            row[0]
            for row in value.conn.execute(
                "SELECT content FROM chat_messages WHERE id = ? ORDER BY session_id",
                ("same-id",),
            ).fetchall()
        ] == ["one", "two"]
        assert value.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        value.close()


@pytest.mark.parametrize(
    "provider_columns",
    [(), ("claude_session_id",), ("claude_session_id", "opencode_session_id")],
    ids=["base", "claude", "claude-and-opencode"],
)
def test_migrates_all_committed_session_schema_shapes(
    tmp_path: Path, provider_columns: tuple[str, ...]
):
    db_path = tmp_path / "history.db"
    _create_composite_key_history_database(db_path, provider_columns)

    value = ChatSessionStore(db_path)
    value.connect()
    try:
        session = value.get_session("u1", "history-s1")
        assert session is not None
        assert session["project_id"] is None
        assert session["applied_context_revision"] is None
        for column in provider_columns:
            assert session[column] == f"{column}-value"
        assert [message["content"] for message in value.list_messages("history-s1")] == [
            "preserve"
        ]
        assert _message_primary_key(value.conn) == {"session_id": 1, "id": 2}
        assert value.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        value.close()


def test_migration_is_idempotent_and_preserves_project_data(tmp_path: Path):
    db_path = tmp_path / "idempotent.db"
    first = ChatSessionStore(db_path)
    first.connect()
    project = first.create_project("u1", name="alpha", description="desc", instructions="rules")
    session = first.create_session("u1", title="thread", project_id=project["id"])
    first.append_message("u1", session["id"], role="user", content="hello", message_id="m1")
    version = first.conn.execute("PRAGMA user_version").fetchone()[0]
    first.close()

    second = ChatSessionStore(db_path)
    second.connect()
    try:
        assert second.conn.execute("PRAGMA user_version").fetchone()[0] == version
        assert second.get_project("u1", project["id"])["name"] == "alpha"
        assert second.get_session("u1", session["id"])["project_id"] == project["id"]
        assert [message["content"] for message in second.list_messages(session["id"])] == [
            "hello"
        ]
        assert _message_primary_key(second.conn) == {"session_id": 1, "id": 2}
        assert second.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        second.close()


def test_project_assignment_unassignment_and_user_isolation(store: ChatSessionStore):
    alpha = store.create_project("u1", name="alpha")
    beta = store.create_project("u1", name="beta")
    foreign = store.create_project("u2", name="private")

    assigned = store.create_session("u1", title="assigned", project_id=alpha["id"])
    loose = store.create_session("u1", title="loose")

    assert [item["id"] for item in store.list_sessions("u1", project_id=alpha["id"])] == [
        assigned["id"]
    ]
    assert [item["id"] for item in store.list_sessions("u1", unassigned=True)] == [loose["id"]]

    moved = store.update_session("u1", assigned["id"], project_id=beta["id"])
    assert moved and moved["project_id"] == beta["id"]
    unlinked = store.update_session("u1", assigned["id"], project_id=None)
    assert unlinked and unlinked["project_id"] is None

    assert store.get_project("u1", foreign["id"]) is None
    assert store.update_project("u1", foreign["id"], name="stolen") is None
    assert store.delete_project("u1", foreign["id"]) is False
    with pytest.raises(ValueError):
        store.create_session("u1", title="bad", project_id=foreign["id"])
    with pytest.raises(ValueError):
        store.update_session("u1", loose["id"], project_id=foreign["id"])


def test_deleting_project_unlinks_but_does_not_delete_session_or_messages(
    store: ChatSessionStore,
):
    project = store.create_project("u1", name="temporary")
    session = store.create_session("u1", title="keep me", project_id=project["id"])
    store.set_claude_session_id("u1", session["id"], "claude-old")
    store.set_opencode_session_id("u1", session["id"], "opencode-old")
    store.append_message("u1", session["id"], role="user", content="keep", message_id="m1")

    assert store.delete_project("u1", project["id"]) is True
    assert store.get_project("u1", project["id"]) is None

    remaining = store.get_session("u1", session["id"])
    assert remaining is not None
    assert remaining["project_id"] is None
    assert remaining["applied_context_revision"] is None
    assert remaining["claude_session_id"] is None
    assert remaining["opencode_session_id"] is None
    assert [message["content"] for message in store.list_messages(session["id"])] == ["keep"]
    assert store.conn.execute(
        "SELECT COUNT(*) FROM chat_sessions WHERE id = ?", (session["id"],)
    ).fetchone()[0] == 1


def test_stale_provider_session_ids_cannot_write_back_after_project_move(
    store: ChatSessionStore,
):
    original = store.create_project("u1", name="original")
    target = store.create_project("u1", name="target")
    session = store.create_session("u1", title="moving", project_id=original["id"])
    session_id = session["id"]
    original_revision = original["context_revision"]
    assert store.prepare_project_context(
        "u1", session_id, original["id"], original_revision
    ) is True

    moved = store.update_session("u1", session_id, project_id=target["id"])
    assert moved and moved["project_id"] == target["id"]
    assert store.set_claude_session_id(
        "u1",
        session_id,
        "stale-claude",
        expected_project_id=original["id"],
        expected_context_revision=original_revision,
    ) is False
    assert store.get_claude_session_id("u1", session_id) is None

    assert store.prepare_project_context(
        "u1", session_id, target["id"], target["context_revision"]
    ) is True
    assert store.set_claude_session_id(
        "u1",
        session_id,
        "current-claude",
        expected_project_id=target["id"],
        expected_context_revision=target["context_revision"],
    ) is True
    assert store.get_claude_session_id(
        "u1",
        session_id,
        expected_project_id=original["id"],
        expected_context_revision=original_revision,
    ) is None
    assert store.get_claude_session_id(
        "u1",
        session_id,
        expected_project_id=target["id"],
        expected_context_revision=target["context_revision"],
    ) == "current-claude"


def test_stale_provider_session_ids_cannot_write_back_after_context_prepare(
    store: ChatSessionStore,
):
    project = store.create_project("u1", name="mutable", instructions="v1")
    session = store.create_session("u1", title="revision", project_id=project["id"])
    session_id = session["id"]
    old_revision = project["context_revision"]
    assert store.prepare_project_context(
        "u1", session_id, project["id"], old_revision
    ) is True

    changed = store.update_project("u1", project["id"], instructions="v2")
    assert changed and changed["context_revision"] > old_revision
    new_revision = changed["context_revision"]

    # A running old-revision request must not write a native provider SID after
    # the authoritative Project revision advances, even before the next chat has
    # prepared (and cleared) the new context revision.
    assert store.set_claude_session_id(
        "u1",
        session_id,
        "stale-before-prepare",
        expected_project_id=project["id"],
        expected_context_revision=old_revision,
    ) is False
    assert store.set_opencode_session_id(
        "u1",
        session_id,
        "stale-before-prepare",
        expected_project_id=project["id"],
        expected_context_revision=old_revision,
    ) is False

    assert store.prepare_project_context(
        "u1", session_id, project["id"], new_revision
    ) is True

    assert store.set_opencode_session_id(
        "u1",
        session_id,
        "stale-opencode",
        expected_project_id=project["id"],
        expected_context_revision=old_revision,
    ) is False
    assert store.get_opencode_session_id("u1", session_id) is None
    assert store.set_opencode_session_id(
        "u1",
        session_id,
        "current-opencode",
        expected_project_id=project["id"],
        expected_context_revision=new_revision,
    ) is True
    assert store.get_opencode_session_id(
        "u1",
        session_id,
        expected_project_id=project["id"],
        expected_context_revision=old_revision,
    ) is None
    assert store.get_opencode_session_id(
        "u1",
        session_id,
        expected_project_id=project["id"],
        expected_context_revision=new_revision,
    ) == "current-opencode"


def _add_project_file(
    store: ChatSessionStore,
    *,
    project_id: str,
    file_id: str,
    size_bytes: int = 1,
) -> dict:
    return store.add_project_file(
        "u1",
        project_id,
        display_name=f"{file_id}.md",
        storage_name=f"{file_id}-stored.md",
        media_type="text/markdown",
        size_bytes=size_bytes,
        sha256=f"sha256-{file_id}",
        file_id=file_id,
    )


def test_project_file_provenance_requires_source_session_in_target_project(
    store: ChatSessionStore,
):
    target = store.create_project("u1", name="target")
    other = store.create_project("u1", name="other")
    target_session = store.create_session(
        "u1", title="target session", project_id=target["id"]
    )
    other_session = store.create_session(
        "u1", title="other session", project_id=other["id"]
    )

    accepted = store.add_project_file(
        "u1",
        target["id"],
        display_name="result.json",
        storage_name="result-stored.json",
        media_type="application/json",
        size_bytes=2,
        sha256="sha256-result",
        source_session_id=target_session["id"],
        file_id="result-file",
    )
    assert accepted["source_session_id"] == target_session["id"]
    assert accepted["context_revision"] == target["context_revision"] + 1

    with pytest.raises(ValueError, match="当前不在目标项目中"):
        store.add_project_file(
            "u1",
            target["id"],
            display_name="cross-project.json",
            storage_name="cross-project-stored.json",
            media_type="application/json",
            size_bytes=2,
            sha256="sha256-cross-project",
            source_session_id=other_session["id"],
            file_id="cross-project-file",
        )
    assert store.get_project_file("u1", target["id"], "cross-project-file") is None


def test_file_and_project_deletes_create_durable_cleanup_jobs(
    store: ChatSessionStore,
):
    project = store.create_project("u1", name="cleanup")
    record = _add_project_file(store, project_id=project["id"], file_id="file-1")

    assert store.delete_project_file("u1", project["id"], record["id"]) is True
    assert store.get_project_file("u1", project["id"], record["id"]) is None
    jobs = store.list_storage_cleanup_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == f"file:{project['id']}:file-1-stored.md"
    assert jobs[0]["resource_type"] == "file"
    assert jobs[0]["project_id"] == project["id"]
    assert jobs[0]["storage_name"] == "file-1-stored.md"
    assert jobs[0]["user_id"] == "u1"
    assert jobs[0]["file_count"] == 1
    assert jobs[0]["size_bytes"] == 1
    assert jobs[0]["attempts"] == 0
    assert jobs[0]["last_error"] == ""
    assert store.complete_storage_cleanup(
        resource_type="file",
        project_id=project["id"],
        storage_name="file-1-stored.md",
    ) is True

    assert store.delete_project("u1", project["id"]) is True
    jobs = store.list_storage_cleanup_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == f"project:{project['id']}:"
    assert jobs[0]["resource_type"] == "project"
    assert jobs[0]["project_id"] == project["id"]
    assert jobs[0]["storage_name"] == ""
    assert jobs[0]["user_id"] == "u1"
    assert jobs[0]["file_count"] == 0
    assert jobs[0]["size_bytes"] == 0


def test_cleanup_job_insert_failure_rolls_back_file_metadata_delete(
    store: ChatSessionStore,
    monkeypatch: pytest.MonkeyPatch,
):
    project = store.create_project("u1", name="atomic")
    record = _add_project_file(store, project_id=project["id"], file_id="file-1")
    revision_before = store.get_project("u1", project["id"])["context_revision"]

    def fail_enqueue(*_args, **_kwargs):
        raise sqlite3.OperationalError("injected outbox failure")

    monkeypatch.setattr(store, "_enqueue_storage_cleanup", fail_enqueue)
    with pytest.raises(sqlite3.OperationalError, match="injected outbox failure"):
        store.delete_project_file("u1", project["id"], record["id"])

    assert store.get_project_file("u1", project["id"], record["id"]) is not None
    assert store.get_project("u1", project["id"])["context_revision"] == revision_before
    assert store.list_storage_cleanup_jobs() == []


@pytest.mark.parametrize(
    ("limit_name", "second_project", "expected_message"),
    [
        ("EIDO_PROJECT_MAX_FILES", False, "项目共享资料数量已达上限"),
        ("EIDO_PROJECT_MAX_BYTES", False, "项目共享资料总容量已达上限"),
        ("EIDO_USER_PROJECT_MAX_FILES", True, "当前用户的项目资料数量已达上限"),
        ("EIDO_USER_PROJECT_MAX_BYTES", True, "当前用户的项目资料总容量已达上限"),
    ],
    ids=["project-files", "project-bytes", "user-files", "user-bytes"],
)
def test_project_file_quota_dimensions_are_enforced_atomically(
    store: ChatSessionStore,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    second_project: bool,
    expected_message: str,
):
    for name in (
        "EIDO_PROJECT_MAX_FILES",
        "EIDO_PROJECT_MAX_BYTES",
        "EIDO_USER_PROJECT_MAX_FILES",
        "EIDO_USER_PROJECT_MAX_BYTES",
    ):
        monkeypatch.setattr(settings, name, 1000)
    monkeypatch.setattr(settings, limit_name, 1)

    first = store.create_project("u1", name="first")
    target = store.create_project("u1", name="second") if second_project else first
    _add_project_file(store, project_id=first["id"], file_id="file-1", size_bytes=1)
    target_revision = store.get_project("u1", target["id"])["context_revision"]

    with pytest.raises(ProjectQuotaExceededError, match=expected_message):
        _add_project_file(
            store,
            project_id=target["id"],
            file_id="file-2",
            size_bytes=1,
        )

    assert store.get_project_file("u1", target["id"], "file-2") is None
    assert store.get_project("u1", target["id"])["context_revision"] == target_revision


def test_pending_file_cleanup_continues_to_consume_project_quota(
    store: ChatSessionStore,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "EIDO_PROJECT_MAX_BYTES", 1)
    project = store.create_project("u1", name="pending")
    record = _add_project_file(
        store, project_id=project["id"], file_id="file-1", size_bytes=1
    )

    assert store.delete_project_file("u1", project["id"], record["id"]) is True
    with pytest.raises(ProjectQuotaExceededError, match="项目共享资料总容量已达上限"):
        _add_project_file(
            store, project_id=project["id"], file_id="file-2", size_bytes=1
        )

    assert store.complete_storage_cleanup(
        resource_type="file",
        project_id=project["id"],
        storage_name="file-1-stored.md",
    ) is True
    assert _add_project_file(
        store, project_id=project["id"], file_id="file-2", size_bytes=1
    )


def test_pending_project_cleanup_continues_to_consume_user_quota(
    store: ChatSessionStore,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "EIDO_USER_PROJECT_MAX_BYTES", 1)
    original = store.create_project("u1", name="original")
    _add_project_file(
        store, project_id=original["id"], file_id="file-1", size_bytes=1
    )
    assert store.delete_project("u1", original["id"]) is True

    target = store.create_project("u1", name="target")
    with pytest.raises(
        ProjectQuotaExceededError, match="当前用户的项目资料总容量已达上限"
    ):
        _add_project_file(
            store, project_id=target["id"], file_id="file-2", size_bytes=1
        )

    assert store.complete_project_storage_cleanup(original["id"]) == 1
    assert _add_project_file(
        store, project_id=target["id"], file_id="file-2", size_bytes=1
    )


def test_cleanup_retry_order_rotates_failed_jobs_behind_unattempted_jobs(
    store: ChatSessionStore,
):
    first_id = store.enqueue_storage_cleanup(
        resource_type="file", project_id="project-1", storage_name="first.md"
    )
    second_id = store.enqueue_storage_cleanup(
        resource_type="file", project_id="project-1", storage_name="second.md"
    )
    store.record_storage_cleanup_failure(first_id, "fail once")

    jobs = store.list_storage_cleanup_jobs(limit=1)
    assert [job["id"] for job in jobs] == [second_id]


def test_reenqueued_cleanup_job_backfills_missing_quota_accounting(
    store: ChatSessionStore,
):
    job_id = store.enqueue_storage_cleanup(
        resource_type="file",
        project_id="project-1",
        storage_name="pending.md",
    )
    assert store.enqueue_storage_cleanup(
        resource_type="file",
        project_id="project-1",
        storage_name="pending.md",
        user_id="u1",
        file_count=1,
        size_bytes=42,
    ) == job_id

    jobs = store.list_storage_cleanup_jobs()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id
    assert jobs[0]["user_id"] == "u1"
    assert jobs[0]["file_count"] == 1
    assert jobs[0]["size_bytes"] == 42
    assert jobs[0]["attempts"] == 0
    assert jobs[0]["last_error"] == ""
