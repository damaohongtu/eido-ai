"""Build a bounded prompt history when a provider-native session is rebuilt."""
from __future__ import annotations

from typing import Iterable


def _field(message: object, name: str) -> str:
    value = message.get(name) if isinstance(message, dict) else getattr(message, name, "")
    return str(value or "").strip()


def format_recent_conversation(
    messages: Iterable[object], *, max_chars: int = 12_000
) -> str:
    """Return recent messages before the latest user turn, newest-first bounded.

    Claude Code and OpenCode normally keep their own native history. Project moves,
    context revisions, deleted Projects, or missing native state intentionally clear
    that provider session. In that case this snapshot reconstructs enough persisted
    Eido history to avoid turning the next message into an unrelated first turn.
    """
    normalized = [
        (_field(message, "role"), _field(message, "content"))
        for message in messages
    ]
    latest_user_index = next(
        (index for index in range(len(normalized) - 1, -1, -1) if normalized[index][0] == "user"),
        len(normalized),
    )
    history = normalized[:latest_user_index]
    if not history:
        return ""

    labels = {"user": "用户", "assistant": "助手", "system": "系统"}
    selected: list[str] = []
    used = 0
    for role, content in reversed(history):
        if not content:
            continue
        clipped = content[:4_000]
        block = f"### {labels.get(role, role or '消息')}\n\n{clipped}"
        if selected and used + len(block) > max_chars:
            break
        if len(block) > max_chars:
            block = block[:max_chars]
        selected.append(block)
        used += len(block)

    if not selected:
        return ""
    selected.reverse()
    return (
        "## 当前 Eido 会话的近期历史（原生会话上下文已重建）\n\n"
        "以下是本轮之前的既有对话记录。\n\n"
        + "\n\n".join(selected)
    )
