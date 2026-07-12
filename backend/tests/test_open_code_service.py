import asyncio
import json
import sqlite3

from app.services.chat_session_store import ChatSessionStore
from app.services.open_code_service import (
    OpenCodeService,
    _convert_event,
    _latest_user_text,
)


def _payload(frame: str) -> dict:
    return json.loads(frame.removeprefix("data: ").strip())


def test_convert_opencode_json_events():
    text = _convert_event({"type": "text", "part": {"text": "完成"}})
    assert _payload(text[0]) == {"type": "content", "content": "完成"}

    tool = _convert_event({
        "type": "tool_use",
        "part": {"tool": "bash", "state": {"status": "completed"}},
    })
    assert _payload(tool[0]) == {"type": "thinking", "content": "✓ 工具完成: bash"}

    error = _convert_event({
        "type": "error",
        "error": {"name": "ProviderError", "data": {"message": "bad key"}},
    })
    assert _payload(error[0]) == {"type": "error", "message": "bad key"}


def test_latest_user_text_supports_models_and_dicts():
    assert _latest_user_text([
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": " latest "},
    ]) == "latest"


def test_prompt_includes_workspace_and_skill_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.open_code_service.shutil.which", lambda _: "/bin/opencode")
    skill = tmp_path / "skills" / "system" / "demo" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("---\nname: demo\n---\n", encoding="utf-8")
    cwd = tmp_path / "workspace"
    service = OpenCodeService(tmp_path / "skills", tmp_path, binary="opencode")

    prompt = service._build_prompt("do it", cwd, None, None, resume=False)
    assert str(skill.resolve()) in prompt
    assert str(cwd / "outputs") in prompt
    assert "do it" in prompt


def test_chat_store_migrates_and_persists_opencode_session(tmp_path):
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE chat_sessions (
        id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
        skill_id TEXT, claude_session_id TEXT, created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL)"""
    )
    conn.commit()
    conn.close()

    store = ChatSessionStore(db_path)
    store.connect()
    session = store.create_session("u1")
    assert store.get_opencode_session_id("u1", session["id"]) is None
    assert store.set_opencode_session_id("u1", session["id"], "ses_123")
    assert store.get_opencode_session_id("u1", session["id"]) == "ses_123"
    assert store.get_session("u1", session["id"])["opencode_session_id"] == "ses_123"
    store.close()


def test_execute_stream_runs_cli_and_converts_output(tmp_path):
    fake = tmp_path / "fake-opencode"
    fake.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' '{\"type\":\"tool_use\",\"sessionID\":\"ses_fake\",\"part\":{\"tool\":\"read\",\"state\":{\"status\":\"completed\"}}}'\n"
        "printf '%s\\n' '{\"type\":\"text\",\"sessionID\":\"ses_fake\",\"part\":{\"text\":\"ok\"}}'\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    service = OpenCodeService(tmp_path / "skills", tmp_path, binary=str(fake))

    async def collect():
        return [event async for event in service.execute_stream([
            {"role": "user", "content": "hello"}
        ])]

    events = asyncio.run(collect())
    payloads = [_payload(event) for event in events if event.startswith("data: {")]
    assert {"type": "thinking", "content": "✓ 工具完成: read"} in payloads
    assert {"type": "content", "content": "ok"} in payloads
    assert payloads[-1]["type"] == "workflow_complete"
    assert events[-1] == "data: [DONE]\n\n"
