"""Queue and steer control for active chat sessions."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services import chat_session_store as store_module
from app.services import claude_skill_service as claude_service_module
from app.services import session_workspace as workspace_module
from app.services.chat_execution_guard import get_chat_execution_guard
from app.services.chat_execution_queue import (
    ChatExecutionQueue,
    QueuedChatRun,
)
from app.services.chat_session_store import ChatSessionStore
from app.services.claude_skill_service import ClaudeSkillService, _ClaudeClientEntry
from app.services.session_workspace import SessionWorkspaceManager


class QueueService:
    def __init__(self):
        self.started: list[tuple[str, str]] = []
        self.release_first = asyncio.Event()

    async def execute_stream(self, messages, context=None, **kwargs):
        session_id = kwargs["session_id"]
        prompt = next(message.content for message in reversed(messages) if message.role == "user")
        self.started.append((session_id, prompt))
        if prompt == "first":
            await self.release_first.wait()
        yield f'data: {{"type":"content","content":"done:{prompt}"}}\n\n'
        yield "data: [DONE]\n\n"


@pytest.fixture
def queue_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ChatSessionStore(tmp_path / "sessions.db")
    store.connect()
    workspaces = SessionWorkspaceManager(tmp_path / "workspaces")
    service = QueueService()
    monkeypatch.setattr(store_module, "_instance", store)
    monkeypatch.setattr(workspace_module, "_instance", workspaces)
    monkeypatch.setattr(claude_service_module, "get_claude_skill_service", lambda: service)
    yield store, service
    store.close()


def _run(user: str, session: str, message: str, content: str) -> QueuedChatRun:
    return QueuedChatRun(
        user_id=user,
        session_id=session,
        message_id=message,
        content=content,
        assistant_message_id=f"a-{message}",
        harness="claude_code",
    )


def test_fifo_within_one_session_and_parallel_across_sessions(queue_harness):
    store, service = queue_harness
    session_a = store.create_session("u1", title="A", session_id="session-a")
    session_b = store.create_session("u1", title="B", session_id="session-b")
    queue = ChatExecutionQueue()

    async def exercise():
        queue.enqueue(_run("u1", session_a["id"], "m1", "first"))
        queue.enqueue(_run("u1", session_a["id"], "m2", "second"))
        queue.enqueue(_run("u1", session_b["id"], "m3", "parallel"))
        for _ in range(50):
            if len(service.started) >= 2:
                break
            await asyncio.sleep(0.01)

        assert (session_a["id"], "first") in service.started
        assert (session_b["id"], "parallel") in service.started
        assert (session_a["id"], "second") not in service.started

        service.release_first.set()
        for _ in range(100):
            if queue.count("u1", session_a["id"]) == 0:
                break
            await asyncio.sleep(0.01)

    asyncio.run(exercise())

    assert service.started.index((session_a["id"], "first")) < service.started.index(
        (session_a["id"], "second")
    )
    messages = store.list_messages(session_a["id"], user_id="u1")
    assert [(item["role"], item["content"]) for item in messages] == [
        ("user", "first"),
        ("assistant", "done:first"),
        ("user", "second"),
        ("assistant", "done:second"),
    ]
    get_chat_execution_guard().release(session_a["id"])
    get_chat_execution_guard().release(session_b["id"])


def test_take_removes_only_the_promoted_message_and_preserves_order():
    queue = ChatExecutionQueue()
    first = _run("u1", "session-a", "m1", "first")
    promoted = _run("u1", "session-a", "m2", "promoted")
    third = _run("u1", "session-a", "m3", "third")
    queue.enqueue(first, start=False)
    queue.enqueue(promoted, start=False)
    queue.enqueue(third, start=False)

    assert queue.take("u1", "session-a", "m2") is promoted
    assert [item["message_id"] for item in queue.pending("u1", "session-a")] == [
        "m1",
        "m3",
    ]


def test_steer_writes_to_only_the_target_active_client_without_interrupt(tmp_path: Path):
    class Client:
        def __init__(self):
            self.interrupted = 0
            self.queries: list[str] = []

        async def query(self, content: str):
            self.queries.append(content)

        async def interrupt(self):
            self.interrupted += 1

    service = ClaudeSkillService(tmp_path / "skills", tmp_path)
    active = Client()
    other = Client()
    now = __import__("time").monotonic()
    service._clients[("u1", "s1")] = _ClaudeClientEntry(
        active, ("u1", "s1"), "u1", (), now, now, busy=True
    )
    service._clients[("u1", "s2")] = _ClaudeClientEntry(
        other, ("u1", "s2"), "u1", (), now, now, busy=True
    )

    assert service.can_steer_session("u1", "s1")
    assert asyncio.run(service.steer_session("u1", "s1", "change direction"))
    assert active.queries == ["change direction"]
    assert other.queries == []
    assert active.interrupted == 0
    assert other.interrupted == 0
    assert not service.can_steer_session("u1", "missing")
