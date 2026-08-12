"""Execute every automatic-task run inside a newly-created conversation.

The scheduler lives in the gateway (or the single-tenant process).  A run always
gets its own visible chat session first; local mode writes directly to the local
session store, while Docker sandbox mode creates and executes the conversation
through the owning user's container.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
import uuid
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


class _PersistedTaskFailure(RuntimeError):
    """The task failed after its visible assistant placeholder was updated."""

    def __init__(self, cause: Exception):
        super().__init__(str(cause))
        self.cause = cause


def _is_docker_sandbox() -> bool:
    return (
        settings.EIDO_SANDBOX_MODE or ""
    ).lower() == "docker" and not settings.EIDO_TRUST_GATEWAY


def _conversation_title(task: dict) -> str:
    name = " ".join(str(task.get("name") or "未命名任务").split())
    return f"[自动任务] {name[:60]}"


def _task_messages(task: dict) -> list[dict[str, str]]:
    task_type = task.get("type")
    params = task.get("params") or {}
    if task_type == "skill":
        skill_id = str(params.get("skill_id") or "").strip()
        content = f"请执行技能 {skill_id}" if skill_id else "请执行这个自动技能任务"
        extra = str(params.get("extra_prompt") or "").strip()
        if extra:
            content += f"\n{extra}"
        return [{"role": "user", "content": content}]
    if task_type == "script":
        script_path = str(params.get("script_path") or "").strip()
        args = [str(value) for value in params.get("args") or []]
        command = " ".join([script_path, *args]).strip() or "（未配置脚本）"
        return [{"role": "user", "content": f"执行自动脚本任务：`{command}`"}]

    messages: list[dict[str, str]] = []
    for item in params.get("messages") or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        role = str(item.get("role") or "user")
        if content and role in {"user", "assistant", "system"}:
            messages.append({"role": role, "content": content})
    return messages


async def _sandbox_connection(user_id: str):
    from app.gateway.proxy import get_proxy_client, inject_trust_headers
    from app.gateway.sandbox_manager import get_sandbox_manager

    handle = await get_sandbox_manager().ensure_running(user_id)
    headers = inject_trust_headers({}, user_id)
    headers["Content-Type"] = "application/json"
    return get_proxy_client(), handle.base_url, headers


async def create_task_conversation(task: dict) -> dict:
    """Create the visible conversation before a manual or scheduled run starts."""
    user_id = task["user_id"]
    title = _conversation_title(task)
    if _is_docker_sandbox():
        client, base, headers = await _sandbox_connection(user_id)
        response = await client.post(
            f"{base}/api/v1/sessions/",
            json={"title": title},
            headers=headers,
        )
        response.raise_for_status()
        session = response.json()
    else:
        from app.services.chat_session_store import get_chat_session_store
        from app.services.session_workspace import get_session_workspace_manager

        session = get_chat_session_store().create_session(user_id, title=title)
        get_session_workspace_manager().session_root(session["id"])

    logger.info(
        "[TaskExecutor] 已创建任务会话 task=%s session=%s user=%s",
        task.get("id"),
        session["id"],
        user_id,
    )
    return session


async def _append_local_message(
    user_id: str,
    session_id: str,
    *,
    role: str,
    content: str,
    message_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    from app.services.chat_session_store import get_chat_session_store

    get_chat_session_store().append_message(
        user_id,
        session_id,
        role=role,
        content=content,
        message_id=message_id,
        extra=extra or {},
    )


async def _append_sandbox_message(
    user_id: str,
    session_id: str,
    *,
    role: str,
    content: str,
    message_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    client, base, headers = await _sandbox_connection(user_id)
    response = await client.post(
        f"{base}/api/v1/sessions/{session_id}/messages",
        json={
            "id": message_id,
            "role": role,
            "content": content,
            "extra": extra or {},
        },
        headers=headers,
    )
    response.raise_for_status()


async def _append_task_message(
    user_id: str,
    session_id: str,
    *,
    role: str,
    content: str,
    message_id: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    append = _append_sandbox_message if _is_docker_sandbox() else _append_local_message
    await append(
        user_id,
        session_id,
        role=role,
        content=content,
        message_id=message_id,
        extra=extra,
    )


async def _execute_agent_local(
    task: dict,
    session_id: str,
    messages: list[dict[str, str]],
    *,
    started_event: asyncio.Event | None = None,
) -> None:
    from app.api.v1.endpoints.chat import (
        _accumulate_sse_event,
        _message_extra_from_stream_state,
        _parse_sse_payload,
    )
    from app.services.claude_skill_service import get_claude_skill_service
    from app.services.chat_execution_guard import get_chat_execution_guard

    user_id = task["user_id"]
    guard = get_chat_execution_guard()
    if not guard.try_acquire(session_id):
        raise RuntimeError("自动任务会话正在执行")

    payload_messages: list[dict[str, str]] = []
    assistant_message_id = uuid.uuid4().hex[:12]
    try:
        for message in messages:
            message_id = uuid.uuid4().hex[:12]
            payload = {**message, "id": message_id}
            payload_messages.append(payload)
            await _append_local_message(
                user_id,
                session_id,
                role=message["role"],
                content=message["content"],
                message_id=message_id,
            )
        await _append_local_message(
            user_id,
            session_id,
            role="assistant",
            content="",
            message_id=assistant_message_id,
            extra={"thinking": "自动任务正在启动...", "streaming": True},
        )
        if started_event is not None:
            started_event.set()

        service = get_claude_skill_service()
        if service is None:
            raise RuntimeError("技能服务未初始化")

        state: dict[str, Any] = {"content": ""}
        last_persisted_at = 0.0
        async for event in service.execute_stream(
            payload_messages,
            user_id=user_id,
            session_id=session_id,
        ):
            payload = _parse_sse_payload(event)
            if not payload:
                continue
            _accumulate_sse_event(state, payload)
            now = time.monotonic()
            if now - last_persisted_at >= 0.25:
                await _append_local_message(
                    user_id,
                    session_id,
                    role="assistant",
                    content=(state.get("content") or "").strip(),
                    message_id=assistant_message_id,
                    extra={**_message_extra_from_stream_state(state), "streaming": True},
                )
                last_persisted_at = now

        await _append_local_message(
            user_id,
            session_id,
            role="assistant",
            content=(state.get("content") or "").strip(),
            message_id=assistant_message_id,
            extra={**_message_extra_from_stream_state(state), "streaming": False},
        )
    except Exception as exc:
        await _append_local_message(
            user_id,
            session_id,
            role="assistant",
            content=f"自动任务执行失败：{exc}",
            message_id=assistant_message_id,
            extra={"thinking": "✗ 自动任务执行失败", "streaming": False},
        )
        raise _PersistedTaskFailure(exc) from exc
    finally:
        guard.release(session_id)
        try:
            from app.services.chat_execution_queue import get_chat_execution_queue

            get_chat_execution_queue().kick(user_id, session_id)
        except Exception:
            logger.exception("恢复自动任务会话队列失败 session=%s", session_id)


async def _execute_agent_via_sandbox(
    task: dict,
    session_id: str,
    messages: list[dict[str, str]],
    *,
    started_event: asyncio.Event | None = None,
) -> None:
    user_id = task["user_id"]
    client, base, headers = await _sandbox_connection(user_id)
    payload_messages = [
        {
            "id": uuid.uuid4().hex[:12],
            "role": message["role"],
            "content": message["content"],
        }
        for message in messages
    ]

    # Persist the complete visible turn before returning from "run now". The
    # chat endpoint upserts these same ids, so ordering remains stable.
    for message in payload_messages:
        response = await client.post(
            f"{base}/api/v1/sessions/{session_id}/messages",
            json={**message, "extra": {}},
            headers=headers,
        )
        response.raise_for_status()

    assistant_message_id = uuid.uuid4().hex[:12]
    chat_body = {
        "messages": payload_messages,
        "session_id": session_id,
        "assistant_message_id": assistant_message_id,
    }
    async with client.stream(
        "POST",
        f"{base}/api/v1/chat/chat",
        headers=headers,
        json=chat_body,
    ) as response:
        response.raise_for_status()
        # At this point /chat/chat has acquired the session lease and captured
        # its trusted input history, so the UI placeholder cannot leak into the
        # model prompt.
        placeholder = await client.post(
            f"{base}/api/v1/sessions/{session_id}/messages",
            json={
                "id": assistant_message_id,
                "role": "assistant",
                "content": "",
                "extra": {"thinking": "自动任务正在执行...", "streaming": True},
            },
            headers=headers,
        )
        placeholder.raise_for_status()
        if started_event is not None:
            started_event.set()
        async for _ in response.aiter_bytes():
            pass


async def _execute_script(
    task: dict,
    session_id: str,
    *,
    started_event: asyncio.Event | None = None,
) -> None:
    params = task.get("params") or {}
    script_path = str(params.get("script_path") or "").strip()
    args = [str(value) for value in params.get("args") or []]
    user_id = task["user_id"]
    prompt = _task_messages(task)[0]["content"]
    assistant_message_id = uuid.uuid4().hex[:12]
    await _append_task_message(user_id, session_id, role="user", content=prompt)
    await _append_task_message(
        user_id,
        session_id,
        role="assistant",
        content="",
        message_id=assistant_message_id,
        extra={"thinking": "自动脚本正在执行...", "streaming": True},
    )
    if started_event is not None:
        started_event.set()
    try:
        if not script_path:
            raise ValueError("缺少 script_path")

        result = await asyncio.to_thread(
            subprocess.run,
            [script_path, *args],
            capture_output=True,
            text=True,
            cwd=settings.WORKSPACE_ROOT,
            timeout=300,
        )
        sections = [f"脚本执行完成，退出码：{result.returncode}"]
        if result.stdout.strip():
            sections.append(f"标准输出：\n```text\n{result.stdout.strip()[:100_000]}\n```")
        if result.stderr.strip():
            sections.append(f"标准错误：\n```text\n{result.stderr.strip()[:100_000]}\n```")
        await _append_task_message(
            user_id,
            session_id,
            role="assistant",
            content="\n\n".join(sections),
            message_id=assistant_message_id,
            extra={"streaming": False},
        )
    except Exception as exc:
        await _append_task_message(
            user_id,
            session_id,
            role="assistant",
            content=f"自动任务执行失败：{exc}",
            message_id=assistant_message_id,
            extra={"thinking": "✗ 自动任务执行失败", "streaming": False},
        )
        raise _PersistedTaskFailure(exc) from exc


async def execute_task(
    task: dict,
    *,
    session_id: str | None = None,
    started_event: asyncio.Event | None = None,
) -> dict:
    """Run a task in a new (or explicitly pre-created) visible conversation."""
    task_id = task["id"]
    user_id = task["user_id"]
    conversation = (
        {"id": session_id} if session_id is not None else await create_task_conversation(task)
    )
    session_id = conversation["id"]
    logger.info(
        "[TaskExecutor] 开始执行 task=%s type=%s user=%s session=%s",
        task_id,
        task.get("type"),
        user_id,
        session_id,
    )

    try:
        if task.get("type") == "script":
            await _execute_script(task, session_id, started_event=started_event)
        else:
            messages = _task_messages(task)
            if not messages:
                raise ValueError("任务缺少可执行的对话消息")
            if _is_docker_sandbox():
                await _execute_agent_via_sandbox(
                    task,
                    session_id,
                    messages,
                    started_event=started_event,
                )
            else:
                await _execute_agent_local(
                    task,
                    session_id,
                    messages,
                    started_event=started_event,
                )
        logger.info("[TaskExecutor] task=%s session=%s 执行完成", task_id, session_id)
    except Exception as exc:
        logger.exception("[TaskExecutor] task=%s session=%s 执行失败", task_id, session_id)
        if not isinstance(exc, _PersistedTaskFailure):
            try:
                await _append_task_message(
                    user_id,
                    session_id,
                    role="assistant",
                    content=f"自动任务执行失败：{exc}",
                    extra={"thinking": "✗ 自动任务执行失败", "streaming": False},
                )
            except Exception:
                logger.exception("[TaskExecutor] 无法把失败状态写入会话 %s", session_id)
    finally:
        if started_event is not None:
            started_event.set()
    return conversation
