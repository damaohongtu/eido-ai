"""Automatic tasks always execute in user-visible, persisted conversations."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.api.v1.endpoints import tasks as tasks_endpoint
from app.services import chat_session_store as store_module
from app.services import claude_skill_service as claude_service_module
from app.services import scheduler_service, task_executor
from app.services import session_workspace as workspace_module
from app.services.chat_session_store import ChatSessionStore
from app.services.scheduled_task_store import ScheduledTaskStore
from app.services.session_workspace import SessionWorkspaceManager


class CapturingTaskService:
    def __init__(self, *, failure: str | None = None):
        self.failure = failure
        self.session_ids: list[str | None] = []
        self.messages: list[list[dict]] = []
        self.release = asyncio.Event()
        self.pause = False

    async def execute_stream(
        self,
        messages: list[dict],
        context: str | None = None,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        project_context=None,
    ):
        self.session_ids.append(session_id)
        self.messages.append(list(messages))
        if self.failure:
            raise RuntimeError(self.failure)
        yield 'data: {"type":"thinking","content":"正在执行"}\n\n'
        if self.pause:
            await self.release.wait()
        yield 'data: {"type":"content","content":"任务完成"}\n\n'
        yield "data: [DONE]\n\n"


@dataclass
class TaskHarness:
    store: ChatSessionStore
    service: CapturingTaskService
    workspaces: SessionWorkspaceManager


@pytest.fixture
def task_harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    store = ChatSessionStore(tmp_path / "chat_sessions.db")
    store.connect()
    workspaces = SessionWorkspaceManager(tmp_path / "workspaces")
    service = CapturingTaskService()

    monkeypatch.setattr(store_module, "_instance", store)
    monkeypatch.setattr(workspace_module, "_instance", workspaces)
    monkeypatch.setattr(claude_service_module, "get_claude_skill_service", lambda: service)
    monkeypatch.setattr(task_executor, "_is_docker_sandbox", lambda: False)

    yield TaskHarness(store=store, service=service, workspaces=workspaces)
    store.close()


def _chat_task() -> dict:
    return {
        "id": "task-1",
        "user_id": "user-a",
        "name": "每日行业简报",
        "type": "chat",
        "params": {"messages": [{"role": "user", "content": "生成今天的行业简报"}]},
    }


def test_each_automatic_run_creates_a_distinct_persisted_conversation(
    task_harness: TaskHarness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    scheduled_store = ScheduledTaskStore(tmp_path / "automatic_tasks.db")
    scheduled_store.connect()
    task = scheduled_store.create(
        "user-a",
        "每日行业简报",
        "interval:3600",
        "chat",
        _chat_task()["params"],
    )
    monkeypatch.setattr(scheduler_service, "_store", scheduled_store)
    monkeypatch.setattr(scheduler_service, "_application_loop", None)

    scheduler_service._run_task_job(task["id"])
    scheduler_service._run_task_job(task["id"])

    sessions = task_harness.store.list_sessions("user-a")
    assert len(sessions) == 2
    assert sessions[0]["id"] != sessions[1]["id"]
    assert all(session["title"] == "[自动任务] 每日行业简报" for session in sessions)
    assert set(task_harness.service.session_ids) == {session["id"] for session in sessions}
    assert scheduled_store.get("user-a", task["id"])["last_run_at"] is not None

    for conversation in sessions:
        messages = task_harness.store.list_messages(conversation["id"], user_id="user-a")
        assert [(message["role"], message["content"]) for message in messages] == [
            ("user", "生成今天的行业简报"),
            ("assistant", "任务完成"),
        ]
        assert task_harness.workspaces.session_root(conversation["id"]).is_dir()
    scheduled_store.close()


def test_run_now_returns_new_conversation_and_executes_inside_it(
    task_harness: TaskHarness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    scheduled_store = ScheduledTaskStore(tmp_path / "scheduled_tasks.db")
    scheduled_store.connect()
    scheduled = scheduled_store.create(
        "user-a",
        "立即简报",
        "interval:3600",
        "chat",
        {"messages": [{"role": "user", "content": "立即生成简报"}]},
    )
    monkeypatch.setattr(tasks_endpoint, "_store", scheduled_store)

    async def run_and_wait() -> dict:
        result = await tasks_endpoint.run_task(scheduled["id"], user_id="user-a")
        running = tuple(tasks_endpoint._running_task_runs)
        if running:
            await asyncio.gather(*running)
        return result

    result = asyncio.run(run_and_wait())

    assert result["message"] == "已创建对话并开始执行"
    assert result["session_id"] == result["session"]["id"]
    assert task_harness.store.get_session("user-a", result["session_id"]) is not None
    messages = task_harness.store.list_messages(result["session_id"], user_id="user-a")
    assert messages[-1]["role"] == "assistant"
    assert scheduled_store.get("user-a", scheduled["id"])["last_run_at"] is not None
    scheduled_store.close()


def test_run_now_returns_only_after_running_placeholder_is_visible(
    task_harness: TaskHarness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    scheduled_store = ScheduledTaskStore(tmp_path / "visible_run.db")
    scheduled_store.connect()
    scheduled = scheduled_store.create(
        "user-a",
        "可见执行",
        "interval:3600",
        "chat",
        {"messages": [{"role": "user", "content": "生成耗时简报"}]},
    )
    monkeypatch.setattr(tasks_endpoint, "_store", scheduled_store)
    task_harness.service.pause = True

    async def exercise() -> None:
        result = await tasks_endpoint.run_task(scheduled["id"], user_id="user-a")
        messages = task_harness.store.list_messages(
            result["session_id"], user_id="user-a"
        )
        assert [(message["role"], message["content"]) for message in messages] == [
            ("user", "生成耗时简报"),
            ("assistant", ""),
        ]
        assert messages[-1]["extra"]["streaming"] is True
        assert messages[-1]["extra"]["thinking"] in {
            "自动任务正在启动...",
            "正在执行",
        }

        from app.services.chat_execution_guard import get_chat_execution_guard

        assert get_chat_execution_guard().is_active(result["session_id"])
        task_harness.service.release.set()
        running = tuple(tasks_endpoint._running_task_runs)
        if running:
            await asyncio.gather(*running)
        completed = task_harness.store.list_messages(
            result["session_id"], user_id="user-a"
        )[-1]
        assert completed["content"] == "任务完成"
        assert completed["extra"]["streaming"] is False
        assert not get_chat_execution_guard().is_active(result["session_id"])

    asyncio.run(exercise())
    scheduled_store.close()


def test_execution_failure_is_written_to_the_new_conversation(
    task_harness: TaskHarness,
):
    task_harness.service.failure = "模型不可用"

    conversation = asyncio.run(task_executor.execute_task(_chat_task()))

    messages = task_harness.store.list_messages(conversation["id"], user_id="user-a")
    assert messages[-1]["role"] == "assistant"
    assert messages[-1]["content"] == "自动任务执行失败：模型不可用"


def test_scheduler_worker_submits_execution_to_the_application_loop(
    task_harness: TaskHarness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    scheduled_store = ScheduledTaskStore(tmp_path / "loop_tasks.db")
    scheduled_store.connect()
    task = scheduled_store.create(
        "user-a",
        "跨线程简报",
        "interval:3600",
        "chat",
        _chat_task()["params"],
    )
    monkeypatch.setattr(scheduler_service, "_store", scheduled_store)

    async def invoke_from_worker() -> None:
        monkeypatch.setattr(scheduler_service, "_application_loop", asyncio.get_running_loop())
        completed = await asyncio.to_thread(scheduler_service._run_task_job, task["id"])
        assert completed is None

    asyncio.run(invoke_from_worker())

    assert task_harness.service.session_ids
    assert scheduled_store.get("user-a", task["id"])["last_run_at"] is not None
    scheduled_store.close()
