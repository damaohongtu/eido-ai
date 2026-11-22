"""Typed execution profiles for Claude Code conversations.

The conversation mode is an explicit user choice.  Profiles translate that
choice into Claude Agent SDK capabilities so runtime policy stays in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast

RuntimeMode = Literal["qa", "agent"]

QA_SYSTEM_PROMPT = (
    "你处于简洁问答模式。直接、准确、简短地回答用户的问题。"
    "当前模式不能使用工具、MCP、技能或项目文件，也不能修改文件；"
    "不要声称已经读取、搜索或执行过任何内容。"
    "如果问题必须检查项目、访问外部信息或执行操作，请明确建议用户切换到 Agent 模式。"
)


@dataclass(frozen=True, slots=True)
class ClaudeExecutionProfile:
    mode: RuntimeMode
    tools_enabled: bool
    skills_enabled: bool
    mcp_enabled: bool
    project_context_enabled: bool
    memory_enabled: bool
    max_turns: int | None
    permission_mode: str

    def effort(self, agent_effort: str) -> str:
        return "low" if self.mode == "qa" else agent_effort


PROFILES: dict[RuntimeMode, ClaudeExecutionProfile] = {
    "qa": ClaudeExecutionProfile(
        mode="qa",
        tools_enabled=False,
        skills_enabled=False,
        mcp_enabled=False,
        project_context_enabled=False,
        memory_enabled=False,
        max_turns=1,
        permission_mode="dontAsk",
    ),
    "agent": ClaudeExecutionProfile(
        mode="agent",
        tools_enabled=True,
        skills_enabled=True,
        mcp_enabled=True,
        project_context_enabled=True,
        memory_enabled=True,
        max_turns=None,
        permission_mode="acceptEdits",
    ),
}


def resolve_runtime_mode(value: str | None, *, default: RuntimeMode = "agent") -> RuntimeMode:
    normalized = (value or "").strip().lower()
    if not normalized:
        return default
    if normalized not in PROFILES:
        raise ValueError(f"不支持的会话模式: {value}")
    return cast(RuntimeMode, normalized)


def get_execution_profile(value: str | None) -> ClaudeExecutionProfile:
    return PROFILES[resolve_runtime_mode(value)]
