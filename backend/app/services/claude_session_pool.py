"""Warm Claude Code SDK sessions keyed by Eido user and chat session."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

CLIENT_IDLE_TTL_SEC = 15 * 60.0
CLIENT_POOL_MAX = 32


@dataclass
class ClaudeSessionEntry:
    client: Any
    key: tuple[str, str]
    user_id: str | None
    signature: tuple[Any, ...]
    created_at: float
    last_used: float
    busy: bool = True
    stale: bool = False


class ClaudeSessionPool:
    """Own, reuse, steer and close long-lived Claude SDK subprocesses."""

    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], ClaudeSessionEntry] = {}
        self._cleanup_tasks: set[asyncio.Task] = set()

    @property
    def entries(self) -> dict[tuple[str, str], ClaudeSessionEntry]:
        return self._entries

    @staticmethod
    def _key(user_id: str | None, session_id: str) -> tuple[str, str]:
        return user_id or "", session_id

    @staticmethod
    def _max_age_sec() -> float:
        from app.core.config import settings

        return max(0.0, min(CLIENT_IDLE_TTL_SEC, float(settings.EIDO_USER_TOKEN_TTL) - 30.0))

    async def _close(self, entry: ClaudeSessionEntry) -> None:
        try:
            await entry.client.disconnect()
        except Exception:
            # Closing is best effort during eviction and application shutdown.
            pass

    def _close_later(self, entry: ClaudeSessionEntry) -> None:
        try:
            task = asyncio.create_task(self._close(entry))
        except RuntimeError:
            return
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    async def _prune(self) -> None:
        now = time.monotonic()
        max_age = self._max_age_sec()
        stale: list[ClaudeSessionEntry] = []
        for key, entry in list(self._entries.items()):
            if entry.busy:
                continue
            if (
                entry.stale
                or now - entry.last_used > CLIENT_IDLE_TTL_SEC
                or max_age <= 0
                or now - entry.created_at > max_age
            ) and self._entries.pop(key, None) is entry:
                stale.append(entry)
        for entry in stale:
            self._close_later(entry)

    async def acquire(
        self,
        *,
        options: Any,
        user_id: str | None,
        session_id: str,
        signature: tuple[Any, ...],
    ) -> tuple[ClaudeSessionEntry, bool, float]:
        """Return ``(entry, warm_hit, connect_ms)`` for one exclusive turn."""
        from app.services.claude_sdk_session import ClaudeSdkSession

        await self._prune()
        key = self._key(user_id, session_id)
        now = time.monotonic()
        current = self._entries.get(key)
        max_age = self._max_age_sec()
        if (
            current
            and not current.busy
            and not current.stale
            and current.signature == signature
            and max_age > 0
            and now - current.created_at <= max_age
        ):
            current.busy = True
            return current, True, 0.0

        if current is not None:
            if current.busy:
                raise RuntimeError(f"Claude session 正在执行: {session_id}")
            self._entries.pop(key, None)
            await self._close(current)

        started = time.perf_counter()
        client = ClaudeSdkSession(options=options)
        await client.connect()
        connect_ms = (time.perf_counter() - started) * 1000
        now = time.monotonic()
        entry = ClaudeSessionEntry(
            client=client,
            key=key,
            user_id=user_id,
            signature=signature,
            created_at=now,
            last_used=now,
        )
        self._entries[key] = entry

        candidates = sorted(
            (item for item in self._entries.values() if not item.busy and item is not entry),
            key=lambda item: item.last_used,
        )
        while len(self._entries) > CLIENT_POOL_MAX and candidates:
            victim = candidates.pop(0)
            if self._entries.pop(victim.key, None) is victim:
                self._close_later(victim)
        return entry, False, connect_ms

    async def release(self, entry: ClaudeSessionEntry, *, healthy: bool) -> None:
        entry.busy = False
        entry.last_used = time.monotonic()
        if (not healthy or entry.stale) and self._entries.pop(entry.key, None) is entry:
            await self._close(entry)

    def reset_session(self, session_id: str) -> None:
        for key, entry in list(self._entries.items()):
            if key[1] != session_id:
                continue
            entry.stale = True
            if not entry.busy and self._entries.pop(key, None) is entry:
                self._close_later(entry)

    def reset_user(self, user_id: str | None = None) -> None:
        for key, entry in list(self._entries.items()):
            if user_id is not None and key[0] != user_id:
                continue
            entry.stale = True
            if not entry.busy and self._entries.pop(key, None) is entry:
                self._close_later(entry)

    def can_steer(self, user_id: str | None, session_id: str) -> bool:
        entry = self._entries.get(self._key(user_id, session_id))
        return bool(entry and entry.busy and not entry.stale)

    async def steer(self, user_id: str | None, session_id: str, content: str) -> bool:
        key = self._key(user_id, session_id)
        entry = self._entries.get(key)
        for _ in range(20):
            if entry and entry.busy and not entry.stale:
                break
            await asyncio.sleep(0.05)
            entry = self._entries.get(key)
        if not entry or not entry.busy or entry.stale:
            return False
        await entry.client.query(content)
        return True

    async def interrupt(self, user_id: str | None, session_id: str) -> bool:
        entry = self._entries.get(self._key(user_id, session_id))
        if not entry or not entry.busy or entry.stale:
            return False
        await entry.client.interrupt()
        return True

    async def shutdown(self) -> None:
        entries = list(self._entries.values())
        self._entries.clear()
        if entries:
            await asyncio.gather(*(self._close(entry) for entry in entries), return_exceptions=True)
        if self._cleanup_tasks:
            await asyncio.gather(*tuple(self._cleanup_tasks), return_exceptions=True)
