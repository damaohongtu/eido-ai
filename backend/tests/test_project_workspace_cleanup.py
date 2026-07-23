"""Retryable Project filesystem cleanup tests using only temporary paths."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.services import project_workspace as workspace_module
from app.services.chat_session_store import ChatSessionStore
from app.services.project_workspace import (
    ProjectWorkspaceManager,
    retry_pending_storage_cleanup,
)


def test_symlink_cleanup_unlinks_only_the_link_and_never_follows_its_target(
    tmp_path: Path,
):
    manager = ProjectWorkspaceManager(tmp_path / "projects")

    outside = tmp_path / "outside"
    outside.mkdir()
    outside_sentinel = outside / "keep.txt"
    outside_sentinel.write_text("outside", encoding="utf-8")
    project_link = manager.root / "project-link"
    project_link.symlink_to(outside, target_is_directory=True)

    assert manager.remove_project("project-link") is True
    assert not project_link.is_symlink()
    assert outside_sentinel.read_text(encoding="utf-8") == "outside"

    protected_files = manager.files_dir("protected")
    protected_file = protected_files / "keep.txt"
    protected_file.write_text("protected", encoding="utf-8")

    files_link_project = manager.root / "files-link"
    files_link_project.mkdir()
    (files_link_project / "files").symlink_to(
        protected_files, target_is_directory=True
    )
    with pytest.raises(ValueError, match="项目文件目录不能是符号链接"):
        manager.remove_file("files-link", protected_file.name)
    assert manager.remove_project("files-link") is True
    assert protected_file.read_text(encoding="utf-8") == "protected"

    linked_file = manager.files_dir("file-link") / "linked.txt"
    linked_file.symlink_to(protected_file)
    assert manager.remove_file("file-link", linked_file.name) is True
    assert not linked_file.is_symlink()
    assert protected_file.read_text(encoding="utf-8") == "protected"


def test_failed_file_cleanup_is_recorded_and_succeeds_on_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    store = ChatSessionStore(tmp_path / "chat_sessions.db")
    store.connect()
    manager = ProjectWorkspaceManager(tmp_path / "projects")
    monkeypatch.setattr(workspace_module, "_instance", manager)

    project_id = "project-1"
    storage_name = "asset-stored.md"
    destination = manager.file_path(project_id, storage_name, create_parent=True)
    destination.write_text("durable", encoding="utf-8")
    job_id = store.enqueue_storage_cleanup(
        resource_type="file",
        project_id=project_id,
        storage_name=storage_name,
    )
    real_remove_file = manager.remove_file
    attempts = 0

    def flaky_remove_file(value_project_id: str, value_storage_name: str) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("injected filesystem failure")
        return real_remove_file(value_project_id, value_storage_name)

    monkeypatch.setattr(manager, "remove_file", flaky_remove_file)
    try:
        assert retry_pending_storage_cleanup(store) == {
            "completed": 0,
            "failed": 1,
            "missing": 0,
        }
        assert destination.is_file()
        failed_job = store.list_storage_cleanup_jobs()[0]
        assert failed_job["id"] == job_id
        assert failed_job["attempts"] == 1
        assert failed_job["last_error"] == "injected filesystem failure"

        assert retry_pending_storage_cleanup(store) == {
            "completed": 1,
            "failed": 0,
            "missing": 0,
        }
        assert not destination.exists()
        assert store.list_storage_cleanup_jobs() == []
    finally:
        store.close()


def test_startup_reconcile_removes_only_server_generated_orphans(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    store = ChatSessionStore(tmp_path / "chat_sessions.db")
    store.connect()
    manager = ProjectWorkspaceManager(tmp_path / "projects")
    monkeypatch.setattr(workspace_module, "_instance", manager)
    project = store.create_project("u1", name="reconcile")
    files_dir = manager.files_dir(project["id"])
    final_orphan = files_dir / ("a" * 32 + ".md")
    temp_orphan = files_dir / ("." + "b" * 32 + ".csv." + "c" * 32 + ".upload")
    manual_file = files_dir / "manual-recovery.md"
    final_orphan.write_bytes(b"final")
    temp_orphan.write_bytes(b"temp")
    manual_file.write_bytes(b"manual")

    try:
        result = retry_pending_storage_cleanup(store)
        assert result == {"completed": 2, "failed": 0, "missing": 0}
        assert not final_orphan.exists()
        assert not temp_orphan.exists()
        assert manual_file.read_bytes() == b"manual"
        assert store.list_storage_cleanup_jobs() == []
    finally:
        store.close()


@pytest.mark.parametrize(
    "storage_name",
    [
        "d" * 32 + ".pptx",
        "." + "e" * 32 + ".png." + "f" * 32 + ".import",
    ],
)
def test_startup_reconcile_removes_orphans_for_expanded_project_file_formats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    storage_name: str,
):
    store = ChatSessionStore(tmp_path / "chat_sessions.db")
    store.connect()
    manager = ProjectWorkspaceManager(tmp_path / "projects")
    monkeypatch.setattr(workspace_module, "_instance", manager)
    project = store.create_project("u1", name="expanded formats")
    orphan = manager.files_dir(project["id"]) / storage_name
    orphan.write_bytes(b"orphan")

    try:
        assert retry_pending_storage_cleanup(store) == {
            "completed": 1,
            "failed": 0,
            "missing": 0,
        }
        assert not orphan.exists()
        assert store.list_storage_cleanup_jobs() == []
    finally:
        store.close()


def test_startup_reconcile_isolates_one_unreadable_project_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    store = ChatSessionStore(tmp_path / "chat_sessions.db")
    store.connect()
    manager = ProjectWorkspaceManager(tmp_path / "projects")
    monkeypatch.setattr(workspace_module, "_instance", manager)
    broken = store.create_project("u1", name="broken")
    healthy = store.create_project("u1", name="healthy")
    broken_orphan = manager.files_dir(broken["id"]) / ("a" * 32 + ".md")
    healthy_orphan = manager.files_dir(healthy["id"]) / ("b" * 32 + ".md")
    broken_orphan.write_bytes(b"keep for a later retry")
    healthy_orphan.write_bytes(b"remove now")
    real_enqueue = workspace_module._enqueue_project_orphans

    def fail_one_directory(store_arg, project_path, project_owners, file_keys):
        if project_path.name == broken["id"]:
            raise OSError("injected unreadable directory")
        return real_enqueue(store_arg, project_path, project_owners, file_keys)

    monkeypatch.setattr(
        workspace_module, "_enqueue_project_orphans", fail_one_directory
    )
    try:
        assert retry_pending_storage_cleanup(store) == {
            "completed": 1,
            "failed": 1,
            "missing": 0,
        }
        assert broken_orphan.is_file()
        assert not healthy_orphan.exists()
    finally:
        store.close()


def test_periodic_cleanup_does_not_scan_an_active_upload_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    store = ChatSessionStore(tmp_path / "chat_sessions.db")
    store.connect()
    manager = ProjectWorkspaceManager(tmp_path / "projects")
    monkeypatch.setattr(workspace_module, "_instance", manager)
    project = store.create_project("u1", name="active upload")
    temp_file = manager.files_dir(project["id"]) / (
        "." + "d" * 32 + ".pdf." + "e" * 32 + ".upload"
    )
    temp_file.write_bytes(b"in progress")

    try:
        assert retry_pending_storage_cleanup(
            store, reconcile_orphans=False
        ) == {"completed": 0, "failed": 0, "missing": 0}
        assert temp_file.read_bytes() == b"in progress"
    finally:
        store.close()


def test_stale_project_job_does_not_clear_active_projects_file_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    store = ChatSessionStore(tmp_path / "chat_sessions.db")
    store.connect()
    manager = ProjectWorkspaceManager(tmp_path / "projects")
    monkeypatch.setattr(workspace_module, "_instance", manager)
    project = store.create_project("u1", name="active")
    storage_name = "orphan.md"
    orphan = manager.file_path(project["id"], storage_name, create_parent=True)
    orphan.write_bytes(b"pending")
    store.enqueue_storage_cleanup(
        resource_type="project", project_id=project["id"], user_id="u1"
    )
    store.enqueue_storage_cleanup(
        resource_type="file",
        project_id=project["id"],
        storage_name=storage_name,
        user_id="u1",
        file_count=1,
        size_bytes=len(b"pending"),
    )

    try:
        assert retry_pending_storage_cleanup(
            store, limit=1, reconcile_orphans=False
        ) == {"completed": 1, "failed": 0, "missing": 0}
        jobs = store.list_storage_cleanup_jobs()
        assert [(job["resource_type"], job["storage_name"]) for job in jobs] == [
            ("file", storage_name)
        ]
        assert orphan.is_file()

        assert retry_pending_storage_cleanup(
            store, reconcile_orphans=False
        ) == {"completed": 1, "failed": 0, "missing": 0}
        assert not orphan.exists()
    finally:
        store.close()
