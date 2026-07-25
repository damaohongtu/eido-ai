"""Project API contract tests.

Every fixture uses a temporary SQLite database and temporary workspace roots.
The repository's ``.eido`` directory must never be opened by this module.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient as FastAPITestClient

from app.api.v1.endpoints import chat, projects, sessions, workspace
from app.core.auth import get_current_user_id
from app.core.config import settings
from app.services import chat_session_store as store_module
from app.services import claude_skill_service as claude_service_module
from app.services import open_harness_service as open_harness_service_module
from app.services import project_context as project_context_module
from app.services import project_workspace as project_workspace_module
from app.services.chat_session_store import ChatSessionStore
from app.services.chat_execution_guard import get_chat_execution_guard
from app.services.project_context import ProjectContext
from app.services.project_workspace import (
    ProjectWorkspaceManager,
    retry_pending_storage_cleanup,
)
from app.services.session_workspace import SessionWorkspaceManager


class CapturingChatService:
    """Minimal streaming harness that records the trusted Project snapshot."""

    def __init__(self):
        self.project_context: ProjectContext | None = None
        self.reset_sessions: list[str] = []
        self.messages: list = []

    def reset_session(self, session_id: str) -> None:
        self.reset_sessions.append(session_id)

    async def execute_stream(
        self,
        messages: list,
        context: str | None = None,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        project_context: ProjectContext | None = None,
    ):
        self.project_context = project_context
        self.messages = list(messages)
        yield 'data: {"type":"content","content":"context received"}\n\n'
        yield "data: [DONE]\n\n"


@dataclass
class ProjectApiHarness:
    client: FastAPITestClient
    identity: dict[str, str]
    store: ChatSessionStore
    session_workspaces: SessionWorkspaceManager
    project_workspaces: ProjectWorkspaceManager
    chat_service: CapturingChatService

    def login_as(self, user_id: str) -> None:
        self.identity["user_id"] = user_id


@pytest.fixture
def project_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build only the Project/Session routers around isolated dependencies."""
    store = ChatSessionStore(tmp_path / "chat_sessions.db")
    store.connect()
    session_workspaces = SessionWorkspaceManager(tmp_path / "workspaces")
    project_workspaces = ProjectWorkspaceManager(tmp_path / "projects")
    chat_service = CapturingChatService()

    # get_chat_session_store() resolves this module singleton at request time.
    monkeypatch.setattr(store_module, "_instance", store)
    monkeypatch.setattr(
        sessions, "get_session_workspace_manager", lambda: session_workspaces
    )
    monkeypatch.setattr(
        projects, "get_session_workspace_manager", lambda: session_workspaces
    )
    monkeypatch.setattr(
        projects, "get_project_workspace_manager", lambda: project_workspaces
    )
    monkeypatch.setattr(chat, "get_session_workspace_manager", lambda: session_workspaces)
    monkeypatch.setattr(
        workspace, "get_session_workspace_manager", lambda: session_workspaces
    )
    monkeypatch.setattr(
        project_context_module,
        "get_project_workspace_manager",
        lambda: project_workspaces,
    )
    monkeypatch.setattr(
        claude_service_module, "get_claude_skill_service", lambda: chat_service
    )
    monkeypatch.setattr(
        open_harness_service_module, "get_open_harness_service", lambda: chat_service
    )

    identity = {"user_id": "user-a"}
    app = FastAPI()
    app.include_router(projects.router, prefix="/api/v1/projects")
    app.include_router(sessions.router, prefix="/api/v1/sessions")
    app.include_router(chat.router, prefix="/api/v1/chat")
    app.include_router(workspace.router, prefix="/api/v1/workspace")
    app.dependency_overrides[get_current_user_id] = lambda: identity["user_id"]

    with FastAPITestClient(app) as client:
        yield ProjectApiHarness(
            client=client,
            identity=identity,
            store=store,
            session_workspaces=session_workspaces,
            project_workspaces=project_workspaces,
            chat_service=chat_service,
        )
    store.close()


def _create_project(harness: ProjectApiHarness, name: str = "Research") -> dict:
    response = harness.client.post(
        "/api/v1/projects/",
        json={
            "name": name,
            "description": "Quarterly research",
            "instructions": "Prefer primary sources.",
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_session(
    harness: ProjectApiHarness,
    *,
    title: str,
    project_id: str | None = None,
) -> dict:
    payload: dict[str, str | None] = {"title": title}
    if project_id is not None:
        payload["project_id"] = project_id
    response = harness.client.post("/api/v1/sessions/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _assert_restricted_active_preview(response) -> None:
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    csp = response.headers["content-security-policy"]
    directives = {directive.strip() for directive in csp.split(";")}
    assert "sandbox allow-scripts" in directives
    assert "allow-same-origin" not in csp
    assert "script-src 'unsafe-inline' https:" in directives
    assert "connect-src 'none'" in directives
    assert "form-action 'none'" in directives
    assert "object-src 'none'" in directives
    assert "frame-src 'none'" in directives
    assert "base-uri 'none'" in directives


def test_project_upload_openapi_declares_binary_multipart_file(
    project_api: ProjectApiHarness,
):
    operation = project_api.client.get("/openapi.json").json()["paths"][
        "/api/v1/projects/{project_id}/files"
    ]["post"]
    request_body = operation["requestBody"]
    assert request_body["required"] is True
    schema = request_body["content"]["multipart/form-data"]["schema"]
    assert schema["required"] == ["file"]
    assert schema["properties"]["file"] == {
        "type": "string",
        "format": "binary",
    }


def test_project_crud_filters_and_cross_user_isolation(project_api: ProjectApiHarness):
    project = _create_project(project_api)
    project_id = project["id"]
    assert project["user_id"] == "user-a"
    assert project["session_count"] == 0
    # Empty Projects are metadata-only; the shared-files directory is created lazily.
    assert not (project_api.project_workspaces.root / project_id).exists()

    assigned = _create_session(
        project_api, title="Assigned", project_id=project_id
    )
    unassigned = _create_session(project_api, title="Unassigned")

    by_project = project_api.client.get(
        "/api/v1/sessions/", params={"project_id": project_id}
    )
    assert by_project.status_code == 200, by_project.text
    assert {item["id"] for item in by_project.json()} == {assigned["id"]}

    without_project = project_api.client.get(
        "/api/v1/sessions/", params={"unassigned": "true"}
    )
    assert without_project.status_code == 200, without_project.text
    assert {item["id"] for item in without_project.json()} == {unassigned["id"]}

    invalid_filter = project_api.client.get(
        "/api/v1/sessions/",
        params={"project_id": project_id, "unassigned": "true"},
    )
    assert invalid_filter.status_code == 400

    patched = project_api.client.patch(
        f"/api/v1/projects/{project_id}",
        json={"name": "Renamed", "archived": True},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Renamed"
    assert patched.json()["archived_at"] is not None
    assert project_api.client.get("/api/v1/projects/").json() == []
    archived = project_api.client.get(
        "/api/v1/projects/", params={"include_archived": "true"}
    )
    assert [item["id"] for item in archived.json()] == [project_id]
    assert project_api.client.post(
        "/api/v1/sessions/",
        json={"title": "Archived", "project_id": project_id},
    ).status_code == 409
    assert project_api.client.post(
        f"/api/v1/projects/{project_id}/files",
        files={"file": ("blocked.md", b"blocked", "text/markdown")},
    ).status_code == 409

    assert project_api.client.post(
        "/api/v1/projects/", json={"name": "   "}
    ).status_code == 400
    assert project_api.client.patch(
        f"/api/v1/projects/{project_id}", json={"name": None}
    ).status_code == 400
    assert project_api.client.patch(
        f"/api/v1/projects/{project_id}", json={"archived": None}
    ).status_code == 400
    assert project_api.client.post(
        "/api/v1/sessions/", json={"title": "Invalid", "project_id": ""}
    ).status_code == 400

    project_api.login_as("user-b")
    assert project_api.client.get(
        f"/api/v1/projects/{project_id}"
    ).status_code == 404
    assert project_api.client.patch(
        f"/api/v1/projects/{project_id}", json={"name": "stolen"}
    ).status_code == 404
    assert project_api.client.delete(
        f"/api/v1/projects/{project_id}"
    ).status_code == 404
    assert project_api.client.post(
        "/api/v1/sessions/",
        json={"title": "Foreign project", "project_id": project_id},
    ).status_code == 404


def test_project_freeze_blocks_chat_and_new_or_moved_sessions(
    project_api: ProjectApiHarness,
):
    project = _create_project(project_api)
    assigned = _create_session(
        project_api, title="Assigned", project_id=project["id"]
    )
    unassigned = _create_session(project_api, title="Unassigned")
    guard = get_chat_execution_guard()
    freeze = guard.try_acquire_project_exclusive(project["id"])
    assert freeze is not None

    try:
        create = project_api.client.post(
            "/api/v1/sessions/",
            json={"title": "Blocked", "project_id": project["id"]},
        )
        assert create.status_code == 409

        move = project_api.client.patch(
            f"/api/v1/sessions/{unassigned['id']}",
            json={"project_id": project["id"]},
        )
        assert move.status_code == 409

        chat_response = _send_context_chat(project_api, assigned["id"])
        assert chat_response.status_code == 409
    finally:
        guard.release_project(freeze)


def test_workspace_delete_respects_session_execution_guard(
    project_api: ProjectApiHarness,
):
    session = _create_session(project_api, title="Busy workspace")
    session_id = session["id"]
    output = project_api.session_workspaces.outputs_dir(session_id) / "result.csv"
    output.write_text("value\n42\n", encoding="utf-8")
    guard = get_chat_execution_guard()
    assert guard.try_acquire(session_id)

    try:
        blocked = project_api.client.delete(
            "/api/v1/workspace/file",
            params={"session_id": session_id, "path": "outputs/result.csv"},
        )
        assert blocked.status_code == 409, blocked.text
        assert output.is_file()
    finally:
        guard.release(session_id)

    deleted = project_api.client.delete(
        "/api/v1/workspace/file",
        params={"session_id": session_id, "path": "outputs/result.csv"},
    )
    assert deleted.status_code == 200, deleted.text
    assert not output.exists()


@pytest.mark.parametrize(
    "filename",
    [
        "report.html",
        "report.xht",
        "diagram.svg",
        "diagram.svgz",
        "transform.xsl",
        "transform.xslt",
    ],
)
def test_workspace_active_file_preview_is_inline_and_sandboxed(
    project_api: ProjectApiHarness,
    filename: str,
):
    session = _create_session(project_api, title=f"Preview {filename}")
    session_id = session["id"]
    output = project_api.session_workspaces.outputs_dir(session_id) / filename
    output.write_text(
        "<html><script>fetch('https://example.com')</script><p>preview</p></html>",
        encoding="utf-8",
    )
    params = {"session_id": session_id, "path": f"outputs/{filename}"}

    ordinary = project_api.client.get("/api/v1/workspace/file", params=params)
    assert ordinary.status_code == 200, ordinary.text
    assert ordinary.headers["content-disposition"].startswith("attachment")
    assert "content-security-policy" not in ordinary.headers

    previewed = project_api.client.get(
        "/api/v1/workspace/file", params={**params, "preview": "true"}
    )
    assert previewed.status_code == 200, previewed.text
    assert previewed.headers["content-disposition"].startswith("inline")
    _assert_restricted_active_preview(previewed)

    downloaded = project_api.client.get(
        "/api/v1/workspace/file",
        params={**params, "preview": "true", "download": "true"},
    )
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-disposition"].startswith("attachment")
    assert "content-security-policy" not in downloaded.headers

    project_api.login_as("user-b")
    unauthorized = project_api.client.get(
        "/api/v1/workspace/file", params={**params, "preview": "true"}
    )
    assert unauthorized.status_code == 404


def test_workspace_display_filename_cannot_override_real_media_type(
    project_api: ProjectApiHarness,
):
    session = _create_session(project_api, title="MIME confusion")
    session_id = session["id"]
    output = project_api.session_workspaces.outputs_dir(session_id) / "report.txt"
    output.write_text("<script>document.title='executed'</script>", encoding="utf-8")

    response = project_api.client.get(
        "/api/v1/workspace/file",
        params={
            "session_id": session_id,
            "path": "outputs/report.txt",
            "filename": "report.html",
            "preview": "true",
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["content-disposition"].startswith("inline")
    assert "content-security-policy" not in response.headers


def test_workspace_markdown_preview_is_rendered_and_inert(
    project_api: ProjectApiHarness,
):
    session = _create_session(project_api, title="Markdown preview")
    session_id = session["id"]
    output = project_api.session_workspaces.outputs_dir(session_id) / "report.md"
    output.write_text(
        "# Report\n\n| Item | Value |\n| --- | ---: |\n| Revenue | 42 |\n\n"
        "<script>document.title='unsafe'</script>\n",
        encoding="utf-8",
    )
    params = {"session_id": session_id, "path": "outputs/report.md"}

    ordinary = project_api.client.get("/api/v1/workspace/file", params=params)
    assert ordinary.headers["content-type"].startswith("text/markdown")
    assert ordinary.text.startswith("# Report")

    previewed = project_api.client.get(
        "/api/v1/workspace/file", params={**params, "preview": "true"}
    )
    assert previewed.status_code == 200, previewed.text
    assert previewed.headers["content-type"].startswith("text/html")
    assert previewed.headers["content-disposition"] == "inline"
    assert "script-src 'none'" in previewed.headers["content-security-policy"]
    assert "<h1>Report</h1>" in previewed.text
    assert "<table>" in previewed.text
    assert "<script>document.title='unsafe'</script>" not in previewed.text
    assert "&lt;script&gt;" in previewed.text


def test_delete_project_unbinds_but_preserves_session_messages_and_workspace(
    project_api: ProjectApiHarness,
):
    project = _create_project(project_api)
    session = _create_session(
        project_api, title="Keep me", project_id=project["id"]
    )
    session_id = session["id"]
    sentinel = project_api.session_workspaces.outputs_dir(session_id) / "keep.txt"
    sentinel.write_text("session artifact", encoding="utf-8")

    message = project_api.client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={"id": "same-client-id", "role": "user", "content": "hello"},
    )
    assert message.status_code == 200, message.text
    assert project_api.store.set_claude_session_id("user-a", session_id, "claude-1")
    assert project_api.store.set_opencode_session_id("user-a", session_id, "opencode-1")

    response = project_api.client.delete(f"/api/v1/projects/{project['id']}")
    assert response.status_code == 200, response.text
    assert response.json() == {
        "deleted": True,
        "sessions_preserved": True,
        "cleanup_pending": False,
    }

    detail = project_api.client.get(f"/api/v1/sessions/{session_id}")
    assert detail.status_code == 200, detail.text
    retained = detail.json()
    assert retained["project_id"] is None
    assert retained["applied_context_revision"] is None
    assert retained["claude_session_id"] is None
    assert retained["opencode_session_id"] is None
    assert [item["content"] for item in retained["messages"]] == ["hello"]
    assert sentinel.read_text(encoding="utf-8") == "session artifact"
    assert project_api.chat_service.reset_sessions == [session_id]


def _send_context_chat(
    project_api: ProjectApiHarness,
    session_id: str,
    *,
    assistant_message_id: str = "assistant-context",
    harness: str = "claude_code",
    messages: list[dict[str, str]] | None = None,
):
    request_messages = messages or [
        {"id": "user-context", "role": "user", "content": "Use the facts"}
    ]
    return project_api.client.post(
        "/api/v1/chat/chat",
        json={
            "messages": request_messages,
            "session_id": session_id,
            "assistant_message_id": assistant_message_id,
            "harness": harness,
        },
    )


def test_project_context_snapshot_includes_owned_shared_files(
    project_api: ProjectApiHarness,
):
    project = _create_project(project_api, name="Context project")
    project_id = project["id"]
    upload = project_api.client.post(
        f"/api/v1/projects/{project_id}/files",
        files={"file": ("facts.md", b"verified facts", "text/markdown")},
    )
    assert upload.status_code == 200, upload.text
    session = _create_session(
        project_api, title="Context session", project_id=project_id
    )

    captured = project_context_module.load_project_context("user-a", session["id"])
    assert captured is not None
    assert captured.id == project_id
    assert captured.name == "Context project"
    assert captured.description == "Quarterly research"
    assert captured.instructions == "Prefer primary sources."
    assert [(name, path.read_bytes()) for name, path in captured.files] == [
        ("facts.md", b"verified facts")
    ]


def test_chat_derives_context_from_session_and_persists_stream_result(
    project_api: ProjectApiHarness,
):
    project = _create_project(project_api, name="Context project")
    session = _create_session(
        project_api, title="Context session", project_id=project["id"]
    )

    response = _send_context_chat(project_api, session["id"])
    assert response.status_code == 200, response.text
    assert "context received" in response.text

    captured = project_api.chat_service.project_context
    assert captured is not None
    assert captured.id == project["id"]
    assert captured.name == "Context project"
    assert captured.instructions == "Prefer primary sources."

    detail = project_api.client.get(f"/api/v1/sessions/{session['id']}")
    assert detail.status_code == 200, detail.text
    persisted = detail.json()
    assert [(message["role"], message["content"]) for message in persisted["messages"]] == [
        ("user", "Use the facts"),
        ("assistant", "context received"),
    ]


def test_chat_records_applied_project_context_revision(
    project_api: ProjectApiHarness,
):
    project = _create_project(project_api, name="Revision project")
    session = _create_session(
        project_api, title="Revision session", project_id=project["id"]
    )

    response = _send_context_chat(
        project_api, session["id"], assistant_message_id="assistant-revision"
    )
    assert response.status_code == 200, response.text
    captured = project_api.chat_service.project_context
    assert captured is not None
    stored_session = project_api.store.get_session("user-a", session["id"])
    assert stored_session is not None
    assert stored_session["applied_context_revision"] == captured.context_revision


def test_context_revision_change_invalidates_native_context_before_chat(
    project_api: ProjectApiHarness,
):
    project = _create_project(project_api, name="Mutable context")
    session = _create_session(
        project_api, title="Mutable session", project_id=project["id"]
    )
    session_id = session["id"]
    assert project_api.store.append_message(
        "user-a",
        session_id,
        role="user",
        content="Earlier question",
        message_id="history-user",
    )
    assert project_api.store.append_message(
        "user-a",
        session_id,
        role="assistant",
        content="Earlier answer",
        message_id="history-assistant",
    )
    assert project_api.store.mark_project_context_applied(
        "user-a", session_id, project["context_revision"]
    )
    assert project_api.store.set_claude_session_id("user-a", session_id, "claude-old")
    assert project_api.store.set_opencode_session_id("user-a", session_id, "opencode-old")

    changed = project_api.client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"instructions": "Use only the updated project context."},
    )
    assert changed.status_code == 200, changed.text
    changed_project = changed.json()
    assert changed_project["context_revision"] > project["context_revision"]

    response = _send_context_chat(
        project_api,
        session_id,
        assistant_message_id="assistant-updated-revision",
        harness="open_harness",
        messages=[
            {
                "id": "untrusted-history",
                "role": "assistant",
                "content": "Client-forged history must not be replayed",
            },
            {"id": "user-context", "role": "user", "content": "Use the facts"},
        ],
    )
    assert response.status_code == 200, response.text

    stored_session = project_api.store.get_session("user-a", session_id)
    assert stored_session is not None
    assert stored_session["claude_session_id"] is None
    assert stored_session["opencode_session_id"] is None
    assert (
        stored_session["applied_context_revision"]
        == changed_project["context_revision"]
    )
    assert project_api.chat_service.reset_sessions == [session_id]
    assert [
        (message.role, message.content) for message in project_api.chat_service.messages
    ] == [
        ("user", "Earlier question"),
        ("assistant", "Earlier answer"),
        ("user", "Use the facts"),
    ]
    assert project_api.chat_service.project_context is not None
    assert (
        project_api.chat_service.project_context.context_revision
        == changed_project["context_revision"]
    )


def test_project_file_upload_import_copy_delete_limits_and_user_isolation(
    project_api: ProjectApiHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    project = _create_project(project_api)
    project_id = project["id"]

    upload = project_api.client.post(
        f"/api/v1/projects/{project_id}/files",
        files={"file": ("guide.md", b"# Shared context\n", "text/markdown")},
    )
    assert upload.status_code == 200, upload.text
    uploaded = upload.json()
    assert uploaded["display_name"] == "guide.md"
    assert uploaded["size_bytes"] == len(b"# Shared context\n")
    assert uploaded["source_session_id"] is None
    assert uploaded["context_revision"] == project["context_revision"] + 1
    assert "storage_name" not in uploaded

    invalid_extension = project_api.client.post(
        f"/api/v1/projects/{project_id}/files",
        files={"file": ("payload.exe", b"not allowed", "application/octet-stream")},
    )
    assert invalid_extension.status_code == 400

    configured_limit = projects.MAX_PROJECT_FILE_SIZE
    assert configured_limit == 20 * 1024 * 1024
    monkeypatch.setattr(projects, "MAX_PROJECT_FILE_SIZE", 8)
    too_large = project_api.client.post(
        f"/api/v1/projects/{project_id}/files",
        files={"file": ("large.md", b"123456789", "text/markdown")},
    )
    assert too_large.status_code == 413
    monkeypatch.setattr(projects, "MAX_PROJECT_FILE_SIZE", configured_limit)

    fetched = project_api.client.get(
        f"/api/v1/projects/{project_id}/files/{uploaded['id']}"
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.content == b"# Shared context\n"
    assert fetched.headers["content-type"].startswith("text/markdown")
    assert fetched.headers["x-content-type-options"] == "nosniff"

    previewed_markdown = project_api.client.get(
        f"/api/v1/projects/{project_id}/files/{uploaded['id']}",
        params={"preview": "true"},
    )
    assert previewed_markdown.status_code == 200, previewed_markdown.text
    assert previewed_markdown.headers["content-type"].startswith("text/html")
    assert "<h1>Shared context</h1>" in previewed_markdown.text
    assert "script-src 'none'" in previewed_markdown.headers["content-security-policy"]

    session = _create_session(
        project_api, title="Source session", project_id=project_id
    )
    source = project_api.session_workspaces.outputs_dir(session["id"]) / "source.csv"
    source.write_bytes(b"period,revenue\nQ1,42\n")
    imported_response = project_api.client.post(
        f"/api/v1/projects/{project_id}/files/import",
        json={
            "session_id": session["id"],
            # Agents commonly report an absolute path; it is accepted only when
            # it resolves inside this exact session's outputs directory.
            "path": str(source),
            "display_name": "source.csv",
        },
    )
    assert imported_response.status_code == 200, imported_response.text
    imported = imported_response.json()
    assert imported["source_session_id"] == session["id"]
    assert imported["context_revision"] == uploaded["context_revision"] + 1

    # Import is a copy: removing the source must not invalidate Project context.
    source.unlink()
    copied = project_api.client.get(
        f"/api/v1/projects/{project_id}/files/{imported['id']}"
    )
    assert copied.status_code == 200, copied.text
    assert copied.content == b"period,revenue\nQ1,42\n"

    traversal = project_api.client.post(
        f"/api/v1/projects/{project_id}/files/import",
        json={"session_id": session["id"], "path": "../../outside.csv"},
    )
    assert traversal.status_code == 403

    uploaded_source = project_api.session_workspaces.uploads_dir(session["id"]) / "input.csv"
    uploaded_source.write_text("not a generated result", encoding="utf-8")
    from_uploads = project_api.client.post(
        f"/api/v1/projects/{project_id}/files/import",
        json={"session_id": session["id"], "path": "uploads/input.csv"},
    )
    assert from_uploads.status_code == 403

    output_link = project_api.session_workspaces.outputs_dir(session["id"]) / "link.csv"
    output_link.symlink_to(uploaded_source)
    symlink_escape = project_api.client.post(
        f"/api/v1/projects/{project_id}/files/import",
        json={"session_id": session["id"], "path": "outputs/link.csv"},
    )
    assert symlink_escape.status_code == 403

    other_project = _create_project(project_api, name="Other")
    other_session = _create_session(
        project_api, title="Other source", project_id=other_project["id"]
    )
    other_output = (
        project_api.session_workspaces.outputs_dir(other_session["id"]) / "other.csv"
    )
    other_output.write_text("other", encoding="utf-8")
    cross_project = project_api.client.post(
        f"/api/v1/projects/{project_id}/files/import",
        json={"session_id": other_session["id"], "path": "outputs/other.csv"},
    )
    assert cross_project.status_code == 409
    assert "不属于目标项目" in cross_project.json()["detail"]

    project_api.login_as("user-b")
    assert project_api.client.get(
        f"/api/v1/projects/{project_id}/files/{uploaded['id']}",
        params={"preview": "true"},
    ).status_code == 404

    project_api.login_as("user-a")
    private_record = project_api.store.get_project_file(
        "user-a", project_id, uploaded["id"], include_storage=True
    )
    assert private_record is not None
    stored_path = project_api.project_workspaces.file_path(
        project_id, private_record["storage_name"]
    )
    assert stored_path.is_file()
    deleted = project_api.client.delete(
        f"/api/v1/projects/{project_id}/files/{uploaded['id']}"
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted": True, "cleanup_pending": False}
    assert not stored_path.exists()
    assert project_api.client.get(
        f"/api/v1/projects/{project_id}/files/{uploaded['id']}"
    ).status_code == 404


def test_project_file_import_rejects_symlinked_workspace_roots(
    project_api: ProjectApiHarness,
):
    project = _create_project(project_api, name="Symlink roots")
    source_session = _create_session(
        project_api, title="Source", project_id=project["id"]
    )
    sibling_session = _create_session(
        project_api, title="Sibling", project_id=project["id"]
    )
    source_root = project_api.session_workspaces.root / source_session["id"]
    source_uploads = source_root / "uploads"
    source_outputs = source_root / "outputs"
    uploaded = source_uploads / "input.csv"
    uploaded.write_text("not generated", encoding="utf-8")

    source_outputs.rmdir()
    source_outputs.symlink_to(source_uploads, target_is_directory=True)
    linked_outputs = project_api.client.post(
        f"/api/v1/projects/{project['id']}/files/import",
        json={"session_id": source_session["id"], "path": "outputs/input.csv"},
    )
    assert linked_outputs.status_code == 403, linked_outputs.text

    source_outputs.unlink()
    source_outputs.mkdir()
    sibling_output = (
        project_api.session_workspaces.outputs_dir(sibling_session["id"])
        / "sibling.csv"
    )
    sibling_output.write_text("other session", encoding="utf-8")
    shutil.rmtree(source_root)
    source_root.symlink_to(sibling_output.parent.parent, target_is_directory=True)
    linked_session = project_api.client.post(
        f"/api/v1/projects/{project['id']}/files/import",
        json={"session_id": source_session["id"], "path": "outputs/sibling.csv"},
    )
    assert linked_session.status_code == 403, linked_session.text


@pytest.mark.parametrize(
    ("filename", "media_type", "force_attachment"),
    [
        ("report.html", "text/html", True),
        ("diagram.svg", "image/svg+xml", True),
        ("report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", True),
        ("notes.txt", "text/plain", False),
        ("data.json", "application/json", False),
        ("chart.png", "image/png", False),
        ("deck.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", True),
    ],
)
def test_generated_result_formats_and_active_content_download_policy(
    project_api: ProjectApiHarness,
    filename: str,
    media_type: str,
    force_attachment: bool,
):
    project = _create_project(project_api, name=f"Formats {filename}")
    uploaded = project_api.client.post(
        f"/api/v1/projects/{project['id']}/files",
        files={"file": (filename, b"generated", "application/octet-stream")},
    )
    assert uploaded.status_code == 200, uploaded.text
    fetched = project_api.client.get(
        f"/api/v1/projects/{project['id']}/files/{uploaded.json()['id']}"
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.headers["content-type"].startswith(media_type)
    disposition = fetched.headers["content-disposition"]
    assert disposition.startswith("attachment" if force_attachment else "inline")
    assert fetched.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("filename", ["report.html", "diagram.svg"])
def test_project_active_file_preview_is_inline_and_sandboxed(
    project_api: ProjectApiHarness,
    filename: str,
):
    project = _create_project(project_api, name=f"Preview {filename}")
    uploaded = project_api.client.post(
        f"/api/v1/projects/{project['id']}/files",
        files={
            "file": (
                filename,
                b"<script>top.location='//example.com'</script>",
                "text/plain",
            )
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    url = f"/api/v1/projects/{project['id']}/files/{uploaded.json()['id']}"

    ordinary = project_api.client.get(url)
    assert ordinary.status_code == 200, ordinary.text
    assert ordinary.headers["content-disposition"].startswith("attachment")
    assert "content-security-policy" not in ordinary.headers

    previewed = project_api.client.get(url, params={"preview": "true"})
    assert previewed.status_code == 200, previewed.text
    assert previewed.headers["content-disposition"].startswith("inline")
    _assert_restricted_active_preview(previewed)

    downloaded = project_api.client.get(url, params={"preview": "true", "download": "true"})
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.headers["content-disposition"].startswith("attachment")
    assert "content-security-policy" not in downloaded.headers

    project_api.login_as("user-b")
    unauthorized = project_api.client.get(url, params={"preview": "true"})
    assert unauthorized.status_code == 404


def test_promoted_output_is_in_next_project_context_and_resets_provider_memory(
    project_api: ProjectApiHarness,
):
    project = _create_project(project_api, name="Promotion context")
    session = _create_session(
        project_api,
        title="Generate and promote",
        project_id=project["id"],
    )
    session_id = session["id"]
    assert project_api.store.mark_project_context_applied(
        "user-a", session_id, project["context_revision"]
    )
    assert project_api.store.set_claude_session_id("user-a", session_id, "claude-old")
    assert project_api.store.set_opencode_session_id("user-a", session_id, "opencode-old")

    result = project_api.session_workspaces.outputs_dir(session_id) / "result.json"
    result.write_text('{"answer": 42}', encoding="utf-8")
    promoted_response = project_api.client.post(
        f"/api/v1/projects/{project['id']}/files/import",
        json={"session_id": session_id, "path": "outputs/result.json"},
    )
    assert promoted_response.status_code == 200, promoted_response.text
    promoted = promoted_response.json()
    assert promoted["context_revision"] == project["context_revision"] + 1

    before_chat = project_api.store.get_session("user-a", session_id)
    assert before_chat is not None
    assert before_chat["applied_context_revision"] == project["context_revision"]

    chat_response = _send_context_chat(
        project_api,
        session_id,
        assistant_message_id="assistant-after-promotion",
        harness="open_harness",
    )
    assert chat_response.status_code == 200, chat_response.text
    captured = project_api.chat_service.project_context
    assert captured is not None
    assert captured.context_revision == promoted["context_revision"]
    assert [(name, path.read_text(encoding="utf-8")) for name, path in captured.files] == [
        ("result.json", '{"answer": 42}')
    ]
    assert project_api.chat_service.reset_sessions == [session_id]
    after_chat = project_api.store.get_session("user-a", session_id)
    assert after_chat is not None
    assert after_chat["applied_context_revision"] == promoted["context_revision"]
    assert after_chat["claude_session_id"] is None
    assert after_chat["opencode_session_id"] is None


def test_cumulative_project_quota_returns_413_without_orphaning_file(
    project_api: ProjectApiHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "EIDO_PROJECT_MAX_BYTES", 4)
    project = _create_project(project_api)
    project_id = project["id"]

    accepted = project_api.client.post(
        f"/api/v1/projects/{project_id}/files",
        files={"file": ("accepted.md", b"1234", "text/markdown")},
    )
    assert accepted.status_code == 200, accepted.text
    rejected = project_api.client.post(
        f"/api/v1/projects/{project_id}/files",
        files={"file": ("rejected.md", b"5", "text/markdown")},
    )
    assert rejected.status_code == 413, rejected.text
    assert rejected.json()["detail"] == "项目共享资料总容量已达上限"

    records = project_api.store.list_project_files(
        "user-a", project_id, include_storage=True
    )
    assert [record["id"] for record in records] == [accepted.json()["id"]]
    assert {
        path.name for path in project_api.project_workspaces.files_dir(project_id).iterdir()
    } == {records[0]["storage_name"]}
    assert project_api.store.list_storage_cleanup_jobs() == []


@pytest.mark.parametrize(
    ("headers", "content"),
    [
        ({}, b"not multipart"),
        (
            {"Content-Type": "multipart/form-data; boundary=invalid"},
            b"not multipart",
        ),
    ],
    ids=["missing-content-type", "malformed-body"],
)
def test_malformed_upload_returns_400_and_releases_guards(
    project_api: ProjectApiHarness,
    headers: dict[str, str],
    content: bytes,
):
    project = _create_project(project_api)
    response = project_api.client.post(
        f"/api/v1/projects/{project['id']}/files",
        headers=headers,
        content=content,
    )
    assert response.status_code == 400, response.text

    guard = get_chat_execution_guard()
    assert guard.try_acquire_user_upload("user-a")
    guard.release_user_upload("user-a")
    exclusive = guard.try_acquire_project_exclusive(project["id"])
    assert exclusive is not None
    guard.release_project(exclusive)


@pytest.mark.parametrize(
    ("range_header", "expected_status"),
    [("items=0-1", 400), ("bytes=999-1000", 416)],
    ids=["malformed", "unsatisfiable"],
)
def test_invalid_file_range_releases_project_lease(
    project_api: ProjectApiHarness,
    range_header: str,
    expected_status: int,
):
    project = _create_project(project_api)
    upload = project_api.client.post(
        f"/api/v1/projects/{project['id']}/files",
        files={"file": ("range.md", b"content", "text/markdown")},
    )
    assert upload.status_code == 200, upload.text

    response = project_api.client.get(
        f"/api/v1/projects/{project['id']}/files/{upload.json()['id']}",
        headers={"Range": range_header},
    )
    assert response.status_code == expected_status, response.text

    guard = get_chat_execution_guard()
    exclusive = guard.try_acquire_project_exclusive(project["id"])
    assert exclusive is not None
    guard.release_project(exclusive)


def test_file_delete_reports_pending_cleanup_and_retry_removes_the_file(
    project_api: ProjectApiHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    project = _create_project(project_api)
    project_id = project["id"]
    upload = project_api.client.post(
        f"/api/v1/projects/{project_id}/files",
        files={"file": ("cleanup.md", b"cleanup", "text/markdown")},
    )
    assert upload.status_code == 200, upload.text
    record = project_api.store.get_project_file(
        "user-a", project_id, upload.json()["id"], include_storage=True
    )
    assert record is not None
    destination = project_api.project_workspaces.file_path(
        project_id, record["storage_name"]
    )
    real_remove_file = project_api.project_workspaces.remove_file

    def fail_remove_file(_project_id: str, _storage_name: str) -> bool:
        raise OSError("injected file delete failure")

    monkeypatch.setattr(project_api.project_workspaces, "remove_file", fail_remove_file)
    deleted = project_api.client.delete(
        f"/api/v1/projects/{project_id}/files/{record['id']}"
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted": True, "cleanup_pending": True}
    assert project_api.store.get_project_file(
        "user-a", project_id, record["id"]
    ) is None
    assert destination.is_file()
    jobs = project_api.store.list_storage_cleanup_jobs()
    assert [(job["resource_type"], job["storage_name"]) for job in jobs] == [
        ("file", record["storage_name"])
    ]

    monkeypatch.setattr(
        project_api.project_workspaces, "remove_file", real_remove_file
    )
    monkeypatch.setattr(
        project_workspace_module, "_instance", project_api.project_workspaces
    )
    assert retry_pending_storage_cleanup(project_api.store) == {
        "completed": 1,
        "failed": 0,
        "missing": 0,
    }
    assert not destination.exists()
    assert project_api.store.list_storage_cleanup_jobs() == []


def test_project_delete_reports_pending_cleanup_and_retry_removes_the_directory(
    project_api: ProjectApiHarness,
    monkeypatch: pytest.MonkeyPatch,
):
    project = _create_project(project_api)
    project_id = project["id"]
    upload = project_api.client.post(
        f"/api/v1/projects/{project_id}/files",
        files={"file": ("cleanup.md", b"cleanup", "text/markdown")},
    )
    assert upload.status_code == 200, upload.text
    project_root = project_api.project_workspaces.project_root(
        project_id, create=False
    )
    assert project_root.is_dir()
    real_remove_project = project_api.project_workspaces.remove_project

    def fail_remove_project(_project_id: str) -> bool:
        raise OSError("injected project delete failure")

    monkeypatch.setattr(
        project_api.project_workspaces, "remove_project", fail_remove_project
    )
    deleted = project_api.client.delete(f"/api/v1/projects/{project_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {
        "deleted": True,
        "sessions_preserved": True,
        "cleanup_pending": True,
    }
    assert project_api.store.get_project("user-a", project_id) is None
    assert project_root.is_dir()
    jobs = project_api.store.list_storage_cleanup_jobs()
    assert [(job["resource_type"], job["project_id"]) for job in jobs] == [
        ("project", project_id)
    ]

    monkeypatch.setattr(
        project_api.project_workspaces, "remove_project", real_remove_project
    )
    monkeypatch.setattr(
        project_workspace_module, "_instance", project_api.project_workspaces
    )
    assert retry_pending_storage_cleanup(project_api.store) == {
        "completed": 1,
        "failed": 0,
        "missing": 0,
    }
    assert not project_root.exists()
    assert project_api.store.list_storage_cleanup_jobs() == []
