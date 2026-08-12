"""Session-scoped queued chat execution.

Queued prompts are kept separate from persisted chat history until their turn
starts.  This preserves the natural user/assistant ordering while still letting
the UI accept more work during an active response.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class QueuedChatRun:
    user_id: str
    session_id: str
    message_id: str
    content: str
    assistant_message_id: str
    harness: str
    context: str | None = None
    delivery_mode: str = "queue"


class ChatExecutionQueue:
    """Run one FIFO queue per session while allowing different sessions in parallel."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queues: dict[tuple[str, str], deque[QueuedChatRun]] = {}
        self._drainers: dict[tuple[str, str], asyncio.Task[None]] = {}

    @staticmethod
    def _key(user_id: str, session_id: str) -> tuple[str, str]:
        return user_id, session_id

    def enqueue(
        self,
        run: QueuedChatRun,
        *,
        start: bool = True,
        front: bool = False,
    ) -> int:
        key = self._key(run.user_id, run.session_id)
        with self._lock:
            queue = self._queues.setdefault(key, deque())
            if front:
                queue.appendleft(run)
                position = 1
            else:
                queue.append(run)
                position = len(queue)
        if start:
            self.kick(run.user_id, run.session_id)
        return position

    def pending(self, user_id: str, session_id: str) -> list[dict[str, Any]]:
        key = self._key(user_id, session_id)
        with self._lock:
            return [
                {
                    "message_id": item.message_id,
                    "content": item.content,
                    "mode": item.delivery_mode,
                    "position": index + 1,
                }
                for index, item in enumerate(self._queues.get(key, ()))
            ]

    def count(self, user_id: str, session_id: str) -> int:
        key = self._key(user_id, session_id)
        with self._lock:
            return len(self._queues.get(key, ()))

    def remove(self, user_id: str, session_id: str, message_id: str) -> bool:
        return self.take(user_id, session_id, message_id) is not None

    def take(
        self,
        user_id: str,
        session_id: str,
        message_id: str,
    ) -> QueuedChatRun | None:
        """Atomically remove and return a pending run, preserving queue order."""
        key = self._key(user_id, session_id)
        with self._lock:
            queue = self._queues.get(key)
            if not queue:
                return None
            removed = next((item for item in queue if item.message_id == message_id), None)
            if removed is None:
                return None
            kept = deque(item for item in queue if item.message_id != message_id)
            if kept:
                self._queues[key] = kept
            else:
                self._queues.pop(key, None)
            return removed

    def kick(self, user_id: str, session_id: str) -> None:
        """Start a drainer when the session is idle; otherwise completion retries it."""
        from app.services.chat_execution_guard import get_chat_execution_guard

        key = self._key(user_id, session_id)
        with self._lock:
            if not self._queues.get(key):
                return
            current = self._drainers.get(key)
            if current is not None and not current.done():
                return
            if get_chat_execution_guard().is_active(session_id):
                return
            try:
                task = asyncio.create_task(self._drain(key))
            except RuntimeError:
                logger.exception("无法启动会话队列 session=%s", session_id)
                return
            self._drainers[key] = task
            task.add_done_callback(
                lambda completed, queue_key=key: self._finish(queue_key, completed)
            )

    def _finish(self, key: tuple[str, str], task: asyncio.Task[None]) -> None:
        with self._lock:
            if self._drainers.get(key) is task:
                self._drainers.pop(key, None)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except Exception:
            logger.exception("会话队列执行器异常 session=%s", key[1])
        self.kick(*key)

    async def _drain(self, key: tuple[str, str]) -> None:
        while True:
            with self._lock:
                queue = self._queues.get(key)
                run = queue.popleft() if queue else None
                if queue is not None and not queue:
                    self._queues.pop(key, None)
            if run is None:
                return
            completed = await _execute_queued_run(run)
            if not completed:
                # A short Project-level write may temporarily block the shared
                # chat lease. Keep one drainer alive and retry without spinning.
                with self._lock:
                    self._queues.setdefault(key, deque()).appendleft(run)
                await asyncio.sleep(0.25)
                continue


async def _execute_queued_run(run: QueuedChatRun) -> bool:
    """Execute one queued prompt and persist it as a normal conversation turn."""
    from app.api.v1.endpoints.chat import (
        _accumulate_sse_event,
        _message_extra_from_stream_state,
        _parse_sse_payload,
    )
    from app.services.chat_execution_guard import get_chat_execution_guard
    from app.services.chat_session_store import get_chat_session_store
    from app.services.project_context import load_project_context
    from app.services.session_workspace import get_session_workspace_manager

    store = get_chat_session_store()
    session = store.get_session(run.user_id, run.session_id)
    if session is None:
        logger.warning("丢弃已删除会话的排队消息 session=%s", run.session_id)
        return True

    guard = get_chat_execution_guard()
    project_id = session.get("project_id")
    if not guard.try_acquire(run.session_id, project_id=project_id):
        return False

    user_extra = {"deliveryMode": run.delivery_mode, "deliveryStatus": "running"}
    try:
        project_context = load_project_context(run.user_id, run.session_id)
        if (
            project_context
            and project_context.applied_context_revision != project_context.context_revision
        ):
            from app.services.claude_skill_service import get_claude_skill_service

            claude_service = get_claude_skill_service()
            if claude_service is not None:
                claude_service.reset_session(run.session_id)
            prepared = store.prepare_project_context(
                run.user_id,
                run.session_id,
                project_context.id,
                project_context.context_revision,
            )
            if prepared is None:
                raise RuntimeError("项目上下文已变化，请重试")
            project_context = load_project_context(run.user_id, run.session_id)

        store.append_message(
            run.user_id,
            run.session_id,
            message_id=run.message_id,
            role="user",
            content=run.content,
            extra=user_extra,
        )
        get_session_workspace_manager().session_root(run.session_id)

        if run.harness == "opencode":
            from app.services.open_code_service import get_open_code_service

            service = get_open_code_service()
        else:
            from app.services.claude_skill_service import get_claude_skill_service

            service = get_claude_skill_service()
        if service is None:
            raise RuntimeError(f"技能服务未初始化（{run.harness}）")

        from app.schemas.chat import Message as ChatMessage

        execution_messages = [
            ChatMessage(id=item["id"], role=item["role"], content=item["content"])
            for item in store.list_messages(run.session_id, user_id=run.user_id, limit=80)
        ]
        state: dict[str, Any] = {"content": ""}
        async for event in service.execute_stream(
            execution_messages,
            run.context,
            user_id=run.user_id,
            session_id=run.session_id,
            project_context=project_context,
        ):
            payload = _parse_sse_payload(event)
            if payload:
                _accumulate_sse_event(state, payload)

        store.append_message(
            run.user_id,
            run.session_id,
            message_id=run.assistant_message_id,
            role="assistant",
            content=(state.get("content") or "").strip(),
            extra=_message_extra_from_stream_state(state),
        )
        store.append_message(
            run.user_id,
            run.session_id,
            message_id=run.message_id,
            role="user",
            content=run.content,
            extra={"deliveryMode": run.delivery_mode, "deliveryStatus": "completed"},
        )
    except Exception as exc:
        logger.exception("排队消息执行失败 session=%s message=%s", run.session_id, run.message_id)
        store.append_message(
            run.user_id,
            run.session_id,
            message_id=run.message_id,
            role="user",
            content=run.content,
            extra={"deliveryMode": run.delivery_mode, "deliveryStatus": "failed"},
        )
        store.append_message(
            run.user_id,
            run.session_id,
            message_id=run.assistant_message_id,
            role="assistant",
            content=f"排队任务执行失败：{exc}",
            extra={},
        )
    finally:
        guard.release(run.session_id)
    return True


_instance = ChatExecutionQueue()


def get_chat_execution_queue() -> ChatExecutionQueue:
    return _instance
