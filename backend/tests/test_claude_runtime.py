"""Behavioral regression tests; no paid API or real user data."""

import asyncio
import json

import pytest
from claude_agent_sdk.types import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
)
from pydantic import SecretStr

from app.core.config import settings
from app.schemas.chat import Message
from app.services.chat_session_store import ChatSessionStore
from app.services.claude_event_adapter import ClaudeEventAdapter
from app.services.claude_prompt import build_prompt
from app.services.claude_runtime import ClaudeRuntime
from app.services.conversation_context import format_recent_conversation, prepare_recovery_context
from app.services.session_workspace import SessionWorkspaceManager


def payloads(events):
    return [json.loads(e[6:]) for e in events if e.startswith("data: {")]


def result(error=False, **kwargs):
    return ResultMessage(
        subtype="success",
        duration_ms=12,
        duration_api_ms=10,
        is_error=error,
        num_turns=1,
        session_id="native-session",
        **kwargs,
    )


def delta(text, parent=None):
    return StreamEvent(
        uuid="event",
        session_id="native-session",
        parent_tool_use_id=parent,
        event={"type": "content_block_delta", "delta": {"type": "text_delta", "text": text}},
    )


def test_partial_text_is_immediate_and_full_message_is_not_duplicated():
    converter = ClaudeEventAdapter()
    assert payloads(converter._convert_message(delta("first"))) == [
        {"type": "content", "content": "first"}
    ]
    assert converter._convert_message(delta("child", "tool-1")) == []
    assert not payloads(
        converter._convert_message(AssistantMessage(content=[TextBlock("first")], model="sonnet"))
    )
    # Next message without partial events must still be displayed.
    assert (
        payloads(
            converter._convert_message(
                AssistantMessage(content=[TextBlock("second")], model="sonnet")
            )
        )[0]["content"]
        == "second"
    )
    assert payloads(converter._convert_message(result(True, result="failed")))[0]["type"] == "error"


def test_recovery_keeps_early_goal_and_retrieves_old_evidence(tmp_path):
    history = [{"role": "user", "content": "原始目标：分析所有行业，保持精确数字。"}]
    history += [{"role": "assistant", "content": f"中间工作 {i}"} for i in range(110)]
    history[10]["content"] = "关键参考：净利润为 987654321 元。"
    history += [{"role": "user", "content": "确认之前净利润的精确数字"}]
    text = format_recent_conversation(history)
    assert "原始目标" in text and "987654321" in text
    assert len(text) <= 12000
    prepare_recovery_context(tmp_path, None, None, history)
    archive = tmp_path / ".eido-context/conversation.jsonl"
    assert len(archive.read_text().splitlines()) == len(history)
    assert "中间工作 80" in archive.read_text()


def test_large_browser_context_keeps_the_tail_on_disk(tmp_path):
    service = ClaudeRuntime(tmp_path / "skills", tmp_path)
    context = "网页正文 " * 5000 + "TAIL-IMPORTANT"
    prompt = build_prompt(
        skills_dir=service.skills_dir,
        fallback_skills_index="",
        cwd=tmp_path,
        latest_user_text="分析",
        context=context,
        resume=True,
    )
    assert len(prompt) < 2000
    assert next((tmp_path / ".eido-context").glob("*.md")).read_text().endswith("TAIL-IMPORTANT")


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    from app.services import chat_session_store, mcp_config_store, session_workspace

    store = ChatSessionStore(tmp_path / "db.sqlite")
    store.connect()
    store.create_session("u1", title="Test", session_id="session1")
    monkeypatch.setattr(chat_session_store, "_instance", store)
    monkeypatch.setattr(
        session_workspace, "_instance", SessionWorkspaceManager(tmp_path / "workspaces")
    )

    class MCP:
        def sdk_servers(self, user):
            return {}, 0

    monkeypatch.setattr(mcp_config_store, "get_mcp_config_store", lambda: MCP())
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("test-not-a-real-key"))
    monkeypatch.setattr(settings, "EIDO_DATA_ROOT", str(tmp_path / "data"))
    monkeypatch.setattr(settings, "ANTHROPIC_MODEL", "")
    monkeypatch.setattr(
        settings,
        "CLAUDE_MODEL_CATALOG_JSON",
        '{"default":"sonnet","models":['
        '{"id":"sonnet","model":"sonnet"},'
        '{"id":"opus","model":"opus"}]}',
    )
    service = ClaudeRuntime(tmp_path / "skills", tmp_path)
    yield service, store
    store.close()


def test_runtime_uses_native_options_persists_init_and_switches_model(runtime, monkeypatch):
    import claude_agent_sdk

    service, store = runtime
    clients = []

    class Client:
        def __init__(self, options):
            self.options = options
            self.prompts = []
            clients.append(self)

        async def connect(self):
            self.owner = asyncio.current_task()

        async def disconnect(self):
            assert self.owner is asyncio.current_task()

        async def query(self, prompt):
            self.prompts.append(prompt)

        async def receive_response(self):
            yield SystemMessage(subtype="init", data={"session_id": "native-session"})
            # SID is durable before any text/tool output.
            assert store.get_claude_session_id("u1", "session1") == "native-session"
            yield delta("hello")
            yield AssistantMessage(content=[TextBlock("hello")], model=self.options.model)
            yield result()

    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", Client)

    async def exercise():
        for i, model in enumerate(["sonnet", "sonnet", "opus"]):
            text = f"question {i}"
            store.append_message("u1", "session1", message_id=f"u{i}", role="user", content=text)
            events = [
                e
                async for e in service.execute_stream(
                    [Message(role="user", content=text)],
                    user_id="u1",
                    session_id="session1",
                    model=model,
                )
            ]
            assert (
                "".join(p["content"] for p in payloads(events) if p["type"] == "content") == "hello"
            )
            assert not [p for p in payloads(events) if p["type"] == "error"]
        assert len(clients) == 2
        assert len(clients[0].prompts) == 2
        assert clients[1].options.resume == "native-session"
        assert clients[1].options.model == "opus"
        assert clients[0].options.include_partial_messages
        assert "PreCompact" in clients[0].options.hooks
        assert json.loads(clients[0].options.settings)["autoMemoryEnabled"]
        await service.shutdown()

    asyncio.run(exercise())


def test_rate_limit_resumes_without_replaying_the_original_task(runtime, monkeypatch):
    import claude_agent_sdk
    from claude_agent_sdk.types import RateLimitEvent, RateLimitInfo

    service, store = runtime
    clients = []

    class Client:
        def __init__(self, options):
            self.options = options
            self.prompts = []
            clients.append(self)

        async def connect(self):
            pass

        async def disconnect(self):
            pass

        async def query(self, prompt):
            self.prompts.append(prompt)

        async def receive_response(self):
            yield SystemMessage(subtype="init", data={"session_id": "native-session"})
            if len(clients) == 1:
                yield RateLimitEvent(
                    rate_limit_info=RateLimitInfo(status="rejected", resets_at=1),
                    uuid="limit",
                    session_id="native-session",
                )
                yield result(True, api_error_status=429)
            else:
                yield AssistantMessage(content=[TextBlock("finished")], model="sonnet")
                yield result()

    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", Client)

    async def exercise():
        store.append_message("u1", "session1", message_id="u1", role="user", content="执行唯一任务")
        events = [
            e
            async for e in service.execute_stream(
                [Message(role="user", content="执行唯一任务")], user_id="u1", session_id="session1"
            )
        ]
        data = payloads(events)
        assert len(clients) == 2
        assert clients[1].options.resume == "native-session"
        assert "执行唯一任务" not in clients[1].prompts[0]
        assert "继续尚未完成" in clients[1].prompts[0]
        assert not any(p["type"] == "error" for p in data)
        assert any("模型额度受限" in p.get("content", "") for p in data)
        assert any(p["type"] == "workflow_complete" for p in data)
        await service.shutdown()

    asyncio.run(exercise())


def test_cancelling_a_stream_closes_the_client_and_releases_pool(runtime, monkeypatch):
    import claude_agent_sdk

    service, store = runtime
    disconnected = []

    class Client:
        def __init__(self, options):
            pass

        async def connect(self):
            self.owner = asyncio.current_task()

        async def disconnect(self):
            assert self.owner is asyncio.current_task()
            disconnected.append(True)

        async def query(self, prompt):
            pass

        async def receive_response(self):
            yield SystemMessage(subtype="init", data={"session_id": "native-session"})
            yield delta("started")
            await asyncio.Event().wait()

    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", Client)

    async def exercise():
        stream = service.execute_stream(
            [Message(role="user", content="test")], user_id="u1", session_id="session1"
        )
        async for event in stream:
            if '"type": "content"' in event:
                break
        await asyncio.wait_for(stream.aclose(), 2)
        assert disconnected and not service.sessions.entries
        assert store.get_claude_session_id("u1", "session1") == "native-session"
        await service.shutdown()

    asyncio.run(exercise())
