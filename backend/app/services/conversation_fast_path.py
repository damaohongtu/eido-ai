"""Zero-model responses for messages that carry no agent task or context."""

import re

_GREETING = re.compile(
    r"^(?:hi|hello|hey|你好|您好|嗨|哈[喽啰]|早上好|下午好|晚上好)[!！,.，。?？~～👋 ]*$",
    re.IGNORECASE,
)


def local_reply(
    text: str, *, has_context: bool, has_project: bool, has_history: bool
) -> str | None:
    """Return a greeting only for a new, context-free conversation."""
    if has_context or has_project or has_history or not _GREETING.fullmatch(text.strip()):
        return None
    return "你好！👋 有什么需要我帮你处理的？"
