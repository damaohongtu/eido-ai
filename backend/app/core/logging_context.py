"""Request-scoped logging context shared by the API and gateway proxy."""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar, Token


TRACE_ID_HEADER = "X-Trace-Id"
_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_trace_id: ContextVar[str] = ContextVar("trace_id", default="-")
_session_id: ContextVar[str] = ContextVar("session_id", default="-")


def new_trace_id() -> str:
    """Return a compact trace ID suitable for logs and HTTP headers."""
    return uuid.uuid4().hex


def resolve_trace_id(value: str | None) -> str:
    """Accept a safe upstream trace ID, otherwise create a fresh one."""
    candidate = (value or "").strip()
    if candidate and _TRACE_ID_RE.fullmatch(candidate):
        return candidate
    return new_trace_id()


def get_trace_id() -> str:
    return _trace_id.get()


def set_trace_id(trace_id: str) -> Token[str]:
    return _trace_id.set(trace_id)


def reset_trace_id(token: Token[str]) -> None:
    _trace_id.reset(token)


def get_session_id() -> str:
    return _session_id.get()


def set_session_id(session_id: str) -> Token[str]:
    return _session_id.set(session_id or "-")


def reset_session_id(token: Token[str]) -> None:
    _session_id.reset(token)


class TraceIdFilter(logging.Filter):
    """Attach the current trace and session IDs to every application log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        record.session_id = get_session_id()
        return True
