"""Prepare and persist interactive chat turns independently of HTTP."""

import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import Literal

from app.core.config import settings
from app.core.logging_context import reset_session_id, set_session_id
from app.schemas.chat import ChatRequest, Message
from app.services.chat.events import ChatEvent, ChatStreamState
from app.services.chat.execution_guard import ChatExecutionGuard, get_chat_execution_guard
from app.services.chat.session_store import ChatSessionStore, get_chat_session_store
from app.services.chat.session_workspace import get_session_workspace_manager
from app.services.claude import runtime as claude_runtime
from app.services.claude.execution_profile import resolve_runtime_mode
from app.services.claude.models import load_model_catalog
from app.services.projects.context import (
    ProjectContext,
    ProjectContextChanged,
    ProjectContextRefreshFailed,
    prepare_turn_context,
)

logger = logging.getLogger(__name__)

ChatRejection = Literal["input", "not_found", "conflict", "unavailable"]


class ChatTurnRejected(RuntimeError):
    def __init__(self, reason: ChatRejection, detail: str):
        super().__init__(detail)
        self.reason = reason


def resolve_chat_model(model: str | None) -> str:
    try:
        return load_model_catalog().find(model).id
    except (OSError, ValueError) as exc:
        logger.warning("模型配置无效: %s", exc)
        raise ChatTurnRejected("input", "模型未配置，请从模型列表选择") from exc


def _release_turn(guard: ChatExecutionGuard, user_id: str, session_id: str) -> None:
    guard.release(session_id)
    try:
        from app.services.chat.execution_queue import get_chat_execution_queue

        get_chat_execution_queue().kick(user_id, session_id)
    except Exception:
        logger.exception("恢复会话队列失败 session=%s", session_id)


@dataclass
class ChatTurn:
    user_id: str
    session_id: str
    message: Message
    assistant_id: str
    context: str | None
    model: str
    runtime_mode: str
    project_id: str | None
    project_context: ProjectContext | None
    runtime: claude_runtime.ClaudeRuntime
    store: ChatSessionStore
    guard: ChatExecutionGuard
    _closed: bool = field(default=False, init=False)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            _release_turn(self.guard, self.user_id, self.session_id)

    async def events(self) -> AsyncGenerator[ChatEvent, None]:
        token = set_session_id(self.session_id)
        state = ChatStreamState()
        try:
            async with aclosing(
                self.runtime.stream_events(
                    [self.message],
                    self.context,
                    user_id=self.user_id,
                    session_id=self.session_id,
                    project_context=self.project_context,
                    project_id=self.project_id,
                    model=self.model,
                    runtime_mode=self.runtime_mode,
                )
            ) as events:
                async for event in events:
                    if isinstance(event, dict):
                        state.apply(event)
                    yield event
        except Exception as exc:
            logger.exception("流式对话失败 session=%s", self.session_id)
            state.record_error(str(exc), stream_failed=True)
            raise
        finally:
            try:
                content = state.content
                if content or state.thinking.strip():
                    self.store.append_message(
                        self.user_id,
                        self.session_id,
                        message_id=self.assistant_id,
                        role="assistant",
                        content=content,
                        extra=state.extra(),
                    )
            except Exception:
                logger.exception("保存 assistant 消息失败 session=%s", self.session_id)
            finally:
                self.close()
                reset_session_id(token)


def prepare_chat_turn(
    user_id: str, request: ChatRequest, *, create_session: bool = False
) -> ChatTurn:
    session_id = request.session_id
    runtime = claude_runtime.get_claude_runtime()
    if runtime is None:
        raise ChatTurnRejected("unavailable", "Claude Code 服务未初始化")
    if not request.messages:
        raise ChatTurnRejected("input", "消息列表为空")
    message = request.messages[-1]
    if message.role != "user" or not message.content.strip():
        raise ChatTurnRejected("input", "最后一条消息必须是非空 user 输入")
    store = get_chat_session_store()
    if create_session:
        session = store.get_or_create_session(
            user_id,
            session_id,
            model=resolve_chat_model(request.model),
            runtime_mode=request.runtime_mode or settings.CLAUDE_DEFAULT_RUNTIME_MODE,
        )
    else:
        session = store.get_session(user_id, session_id)
    if session is None:
        raise ChatTurnRejected("not_found", "会话不存在或不属于当前用户")
    project_id = session.get("project_id")
    guard = get_chat_execution_guard()
    if not guard.try_acquire(session_id, project_id=project_id):
        raise ChatTurnRejected("conflict", "该会话正在执行或所属项目正在变更，请稍后重试")

    try:
        # Re-read after acquiring the lease because the session may have moved.
        session = store.get_session(user_id, session_id)
        if session is None:
            raise ChatTurnRejected("not_found", "会话不存在或不属于当前用户")
        if session.get("project_id") != project_id:
            raise ChatTurnRejected("conflict", "会话所属项目已变化，请重试")
        model = resolve_chat_model(request.model or session.get("model"))
        mode = resolve_runtime_mode(
            request.runtime_mode or session.get("runtime_mode"), default="agent"
        )
        updates = {}
        if request.model and model != session.get("model"):
            updates["model"] = model
        if request.runtime_mode and mode != session.get("runtime_mode", "agent"):
            updates["runtime_mode"] = mode
        if updates:
            store.update_session(user_id, session_id, **updates)
            runtime.reset_session(session_id)

        project_context = None
        if mode == "agent":
            try:
                project_context = prepare_turn_context(
                    user_id, session_id, None if updates else runtime.reset_session
                )
            except ProjectContextChanged as exc:
                raise ChatTurnRejected("conflict", str(exc)) from exc
            except ProjectContextRefreshFailed as exc:
                logger.exception("刷新项目上下文失败 session=%s", session_id)
                raise ChatTurnRejected("unavailable", str(exc)) from exc

        get_session_workspace_manager().session_root(session_id)
        store.append_message(
            user_id, session_id, message_id=message.id, role="user", content=message.content
        )
        return ChatTurn(
            user_id=user_id,
            session_id=session_id,
            message=message,
            assistant_id=request.assistant_message_id or uuid.uuid4().hex[:12],
            context=request.context,
            model=model,
            runtime_mode=mode,
            project_id=project_id,
            project_context=project_context,
            runtime=runtime,
            store=store,
            guard=guard,
        )
    except BaseException:
        _release_turn(guard, user_id, session_id)
        raise
