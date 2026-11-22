"""Events exchanged by the Claude runtime and chat consumers."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class StreamSignal(Enum):
    HEARTBEAT = auto()
    DONE = auto()


ChatEvent = dict[str, Any] | StreamSignal


@dataclass
class ChatStreamState:
    """Build the persisted assistant message from events emitted during a turn."""

    parts: list[str] = field(default_factory=list)
    thinking: str = ""
    thinking_log: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    references: list = field(default_factory=list)
    mermaid: str = ""
    error: str = ""

    @property
    def content(self) -> str:
        return "".join(self.parts).strip()

    def extra(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "thinking": self.thinking,
                "thinkingLog": self.thinking_log,
                "executionSteps": self.steps,
                "references": self.references,
                "workflowMermaid": self.mermaid,
            }.items()
            if value
        }

    def _set_thinking(self, content: str) -> None:
        self.thinking = content
        if content and (not self.thinking_log or self.thinking_log[-1] != content):
            self.thinking_log.append(content)

    def record_error(self, message: str, *, stream_failed: bool = False) -> None:
        self.error = message
        label = "执行失败" if stream_failed else "错误"
        self._set_thinking(f"✗ {label}: {message}")
        self.parts.append(f"\n\n**错误**: {message}")

    def apply(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        data = event.get("data") or {}
        if kind == "content":
            self.parts.append(event.get("content", ""))
        elif kind == "thinking":
            self._set_thinking(event.get("content") or "")
        elif kind == "workflow_graph" and data.get("format") == "mermaid":
            self.mermaid = data.get("content") or self.mermaid
        elif kind == "steps":
            self.steps = [
                {
                    "id": f"step-{index}",
                    "label": capability.get("name", f"步骤 {index + 1}")
                    if isinstance(capability, dict)
                    else str(capability),
                    "type": capability.get("type", "tool")
                    if isinstance(capability, dict)
                    else "tool",
                    "status": "pending",
                    "description": "等待执行...",
                }
                for index, capability in enumerate(data.get("capabilities") or [])
            ]
        elif kind == "step_update":
            current = int(data.get("current_step") or 0) - 1
            if 0 <= current < len(self.steps):
                for step in self.steps[:current]:
                    step["status"] = "completed"
                self.steps[current].update(
                    status="running", description=data.get("thinking") or "执行中..."
                )
            if data.get("thinking"):
                self._set_thinking(data["thinking"])
            self.references = data.get("references") or self.references
        elif kind == "workflow_complete":
            for step in self.steps:
                step["status"] = "completed"
            self.references = data.get("references") or self.references
            self._set_thinking("✓ 执行完成")
        elif kind == "error":
            self.record_error(event.get("message") or "执行失败")
