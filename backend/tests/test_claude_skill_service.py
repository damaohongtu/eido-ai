import asyncio
import json
import sys
import types
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.services.claude_skill_service import ClaudeSkillService
from app.services.project_context import ProjectContext


def _write_skill(root: Path, skill_id: str, *, name: str, description: str) -> Path:
    skill_dir = root / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    return skill_dir


def test_skill_scan_caches_parsed_metadata_and_refreshes_on_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    skills_root = tmp_path / "skills"
    skill_dir = _write_skill(
        skills_root / "system", "demo", name="Demo", description="first"
    )
    service = ClaudeSkillService(skills_root, tmp_path)
    original = service._load_skill
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "_load_skill", counted)

    assert service.scan_skills()[0].description == "first"
    assert calls == 1
    assert service.scan_skills()[0].description == "first"
    assert calls == 1

    # TTL 到期但 stat 指纹未变化时，仍不重新读取正文。
    service._skill_cache[""].expires_at = 0
    assert service.scan_skills()[0].description == "first"
    assert calls == 1

    (skill_dir / "SKILL.md").write_text(
        "---\nname: Demo\ndescription: second and longer\n---\n",
        encoding="utf-8",
    )
    service._skill_cache[""].expires_at = 0
    assert service.scan_skills()[0].description == "second and longer"
    assert calls == 2


def test_native_skill_mapping_preserves_user_override(tmp_path: Path):
    skills_root = tmp_path / "skills"
    system_demo = _write_skill(
        skills_root / "system", "demo", name="System Demo", description="system"
    )
    other = _write_skill(
        skills_root / "system", "other", name="Other", description="other"
    )
    private_demo = _write_skill(
        skills_root / "users" / "u1",
        "demo",
        name="Private Demo",
        description="private",
    )
    cwd = tmp_path / "session"
    service = ClaudeSkillService(skills_root, tmp_path)

    revision, count = service._materialize_native_skills(cwd, user_id="u1")

    native_root = cwd / ".claude" / "skills"
    assert count == 2
    assert len(revision) == 2
    assert (native_root / "demo").is_symlink()
    assert (native_root / "demo").resolve() == private_demo.resolve()
    assert (native_root / "other").resolve() == other.resolve()
    manifest = json.loads(
        (cwd / ".claude" / ".eido-native-skills.json").read_text(encoding="utf-8")
    )
    assert manifest["demo"] == str(private_demo.resolve())
    manifest_path = cwd / ".claude" / ".eido-native-skills.json"
    manifest_mtime = manifest_path.stat().st_mtime_ns
    assert service._materialize_native_skills(cwd, user_id="u1") == (revision, count)
    assert manifest_path.stat().st_mtime_ns == manifest_mtime

    (private_demo / "SKILL.md").unlink()
    service.invalidate_skill_cache(user_id="u1")
    service._materialize_native_skills(cwd, user_id="u1")
    assert (native_root / "demo").resolve() == system_demo.resolve()


def test_resume_prompt_does_not_repeat_project_or_skill_catalog(tmp_path: Path):
    service = ClaudeSkillService(tmp_path / "skills", tmp_path)
    project = ProjectContext(
        id="p1",
        name="Project Alpha",
        description="project description",
        instructions="repeat-me " * 100,
        context_revision=3,
        applied_context_revision=3,
        files=(),
    )

    first = service._build_prompt(
        cwd=tmp_path,
        latest_user_text="first request",
        context=None,
        user_id="u1",
        resume=False,
        project_context=project,
        conversation_history="old history",
        native_skills=True,
    )
    resumed = service._build_prompt(
        cwd=tmp_path,
        latest_user_text="follow up",
        context="pipeline output",
        user_id="u1",
        resume=True,
        project_context=project,
        conversation_history="old history",
        native_skills=True,
    )

    assert "Project Alpha" in first
    assert "old history" in first
    assert "原生 Skills" in first
    assert "可用技能列表" not in first
    assert "Project Alpha" not in resumed
    assert "repeat-me" not in resumed
    assert "old history" not in resumed
    assert "follow up" in resumed
    assert "pipeline output" in resumed


def test_client_pool_reuses_connection_and_reset_disconnects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    clients = []

    class FakeClient:
        def __init__(self, options):
            self.options = options
            self.connected = False
            self.disconnected = False
            clients.append(self)

        async def connect(self):
            self.connected = True

        async def disconnect(self):
            self.disconnected = True

    fake_sdk = types.ModuleType("claude_agent_sdk")
    fake_sdk.ClaudeSDKClient = FakeClient
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)
    service = ClaudeSkillService(tmp_path / "skills", tmp_path)

    async def exercise():
        first, warm, _ = await service._acquire_client(
            options=object(),
            user_id="u1",
            session_id="s1",
            signature=("rev1",),
        )
        assert not warm
        assert first.client.connected
        await service._release_client(first, healthy=True)

        second, warm, _ = await service._acquire_client(
            options=object(),
            user_id="u1",
            session_id="s1",
            signature=("rev1",),
        )
        assert warm
        assert second is first
        await service._release_client(second, healthy=True)

        service.reset_session("s1")
        if service._client_cleanup_tasks:
            await next(iter(service._client_cleanup_tasks))
        assert clients[0].disconnected
        assert not service._clients

    asyncio.run(exercise())


def test_agent_env_passes_settings_credentials_and_disables_auto_memory(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "app.core.user_token.create_user_token", lambda user_id: f"token-for-{user_id}"
    )
    monkeypatch.setattr(settings, "ANTHROPIC_BASE_URL", "https://api.example.test")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", SecretStr("test-api-key"))
    monkeypatch.setattr(settings, "ANTHROPIC_AUTH_TOKEN", SecretStr(""))
    env = ClaudeSkillService._build_agent_env("u1", "s1", "p1")
    assert env["ANTHROPIC_BASE_URL"] == "https://api.example.test"
    assert env["ANTHROPIC_API_KEY"] == "test-api-key"
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert env["API_TIMEOUT_MS"] == str(settings.API_TIMEOUT_MS)
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert env["EIDO_USER_TOKEN"] == "token-for-u1"
    assert env["EIDO_SESSION_ID"] == "s1"
    assert env["EIDO_PROJECT_ID"] == "p1"


def test_agent_auth_requires_noninteractive_credential():
    assert ClaudeSkillService._agent_auth_error({}) is not None
    assert ClaudeSkillService._agent_auth_error({"ANTHROPIC_API_KEY": "key"}) is None
    assert ClaudeSkillService._agent_auth_error({"CLAUDE_CODE_USE_BEDROCK": "1"}) is None
    assert ClaudeSkillService._agent_auth_summary(
        {
            "ANTHROPIC_API_KEY": "must-not-appear-in-summary",
            "ANTHROPIC_BASE_URL": "https://gateway.example.test/anthropic",
        }
    ) == ("api_key", "gateway.example.test")
