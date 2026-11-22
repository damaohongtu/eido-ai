"""Run one turn on a Claude SDK client and translate its native messages."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import aclosing
from typing import TYPE_CHECKING, Any

from app.services.claude.event_adapter import ClaudeEventAdapter
from app.services.claude.prompt import AUTH_FAILURE_MESSAGE, is_not_logged_in_message

if TYPE_CHECKING:
    from claude_agent_sdk import ClaudeAgentOptions

    from app.services.claude.session_pool import ClaudeSessionPool

logger = logging.getLogger(__name__)


class ResumeUnavailable(RuntimeError):
    """The old transcript could not be loaded before the turn started."""


class RateLimitPause(RuntimeError):
    def __init__(self, resets_at: int | float | None):
        self.resets_at = resets_at


def _is_missing_session(error: Exception) -> bool:
    text = str(error).lower()
    return any(
        marker in text
        for marker in (
            "no conversation found",
            "session not found",
            "no session found",
            "could not find session",
            "session does not exist",
        )
    )


async def stream_turn(
    sessions: ClaudeSessionPool,
    prompt: str,
    *,
    options: ClaudeAgentOptions,
    signature: tuple[Any, ...],
    user_id: str | None,
    session_id: str | None,
    save_session: Callable[[str], None],
    runtime_mode: str,
    skill_count: int,
) -> AsyncGenerator[dict[str, Any], None]:
    from claude_agent_sdk import ClaudeSDKError
    from claude_agent_sdk.types import (
        AssistantMessage,
        RateLimitEvent,
        ResultMessage,
        SystemMessage,
    )

    adapter = ClaudeEventAdapter()
    message_seen = False
    first_text = True
    had_error = False
    rate_rejected = False
    rate_reset = None
    started = time.perf_counter()
    try:
        async with sessions.turn(
            options=options, user_id=user_id, session_id=session_id, signature=signature
        ) as turn:
            await turn.client.query(prompt)
            logger.info(
                "  [ClaudeRun] profile=%s resume=%s warm=%s connect_ms=%.1f "
                "prompt_chars=%d skills=%d tools=%d cwd=%s",
                runtime_mode,
                bool(options.resume),
                turn.warm_hit,
                turn.connect_ms,
                len(prompt),
                skill_count,
                len(options.tools or []),
                options.cwd,
            )
            async with aclosing(turn.client.receive_response()) as responses:
                async for message in responses:
                    if not message_seen:
                        logger.info(
                            "  [ClaudeRun] first_message_ms=%.1f warm=%s session=%s",
                            (time.perf_counter() - started) * 1000,
                            turn.warm_hit,
                            session_id or "(none)",
                        )
                        message_seen = True
                    adapter.log_message(message)
                    if isinstance(message, RateLimitEvent):
                        if message.rate_limit_info.status == "rejected":
                            rate_reset = message.rate_limit_info.resets_at
                            rate_rejected = True
                        continue
                    if isinstance(message, AssistantMessage) and message.error == "rate_limit":
                        rate_rejected = True
                        continue
                    if is_not_logged_in_message(message):
                        raise RuntimeError(AUTH_FAILURE_MESSAGE)

                    sid = None
                    if isinstance(message, SystemMessage) and message.subtype == "init":
                        sid = message.data.get("session_id")
                    elif isinstance(message, ResultMessage):
                        sid = message.session_id
                    if sid:
                        save_session(sid)
                    if (
                        isinstance(message, ResultMessage)
                        and message.is_error
                        and (rate_rejected or message.api_error_status == 429)
                    ):
                        raise RateLimitPause(rate_reset)

                    for event in adapter.events(message):
                        had_error |= event["type"] == "error"
                        if first_text and event["type"] == "content":
                            first_text = False
                            logger.info(
                                "[ClaudeRun] first_text_ms=%.1f warm=%s model=%s",
                                (time.perf_counter() - started) * 1000,
                                turn.warm_hit,
                                options.model,
                            )
                        yield event
                    if isinstance(message, ResultMessage):
                        turn.healthy = not message.is_error and not had_error
                        return
            raise RuntimeError("Claude Code 在返回完成状态前断开，会话进度已保留")
    except ClaudeSDKError as exc:
        if options.resume and not message_seen and _is_missing_session(exc):
            raise ResumeUnavailable(str(exc)) from exc
        raise
