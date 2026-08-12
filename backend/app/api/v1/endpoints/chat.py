"""
Chat endpoint：通过 claude_agent_sdk 自动规划执行技能

消息持久化由后端统一负责：
- 请求进入 /chat/chat 后，保存本轮最新 user 消息
- 流式过程中透传 SSE，同时累积 assistant 最终输出和 extra
- 流结束/异常/客户端中断时，保存 assistant 最终状态
"""

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.core.auth import get_current_user_id
from app.core.config import settings
from app.core.logging_context import reset_session_id, set_session_id
from app.schemas.chat import ChatControlRequest, ChatRequest
from app.schemas.chat import Message as ChatMessage
from app.services.chat_execution_guard import get_chat_execution_guard
from app.services.chat_session_store import get_chat_session_store
from app.services.project_context import load_project_context
from app.services.session_workspace import (
    get_session_workspace_manager,
    validate_session_id,
)
from app.services.supported_files import (
    SUPPORTED_FILE_EXTENSIONS,
    supported_extensions_label,
)

router = APIRouter()
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = SUPPORTED_FILE_EXTENSIONS
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _message_extra_from_stream_state(state: dict[str, Any]) -> dict[str, Any]:
    """把 SSE 累积状态转换为 chat_messages.extra_json。"""
    extra: dict[str, Any] = {}
    if state.get("thinking"):
        extra["thinking"] = state["thinking"]
    if state.get("thinking_log"):
        extra["thinkingLog"] = state["thinking_log"]
    if state.get("execution_steps"):
        extra["executionSteps"] = state["execution_steps"]
    if state.get("references"):
        extra["references"] = state["references"]
    if state.get("workflow_mermaid"):
        extra["workflowMermaid"] = state["workflow_mermaid"]
    if state.get("pending_confirmation"):
        extra["pendingConfirmation"] = state["pending_confirmation"]
    return extra


def _set_thinking(state: dict[str, Any], content: str) -> None:
    """更新当前 thinking，并追加到 thinking_log（去重）。"""
    state["thinking"] = content
    if content:
        log = state.setdefault("thinking_log", [])
        if not log or log[-1] != content:
            log.append(content)


def _accumulate_sse_event(state: dict[str, Any], payload: dict[str, Any]) -> None:
    """根据当前 SSE 事件维护 assistant 最终文本与 extra。"""
    event_type = payload.get("type")
    if event_type == "content":
        state["content"] = f"{state.get('content', '')}{payload.get('content', '')}"
    elif event_type == "thinking":
        content = payload.get("content") or ""
        _set_thinking(state, content)
    elif event_type == "workflow_graph":
        data = payload.get("data") or {}
        if data.get("format") == "mermaid" and data.get("content"):
            state["workflow_mermaid"] = data["content"]
    elif event_type == "steps":
        data = payload.get("data") or {}
        capabilities = data.get("capabilities") or []
        state["execution_steps"] = [
            {
                "id": f"step-{i}",
                "label": cap.get("name", f"步骤 {i + 1}") if isinstance(cap, dict) else str(cap),
                "type": cap.get("type", "tool") if isinstance(cap, dict) else "tool",
                "status": "pending",
                "description": "等待执行...",
            }
            for i, cap in enumerate(capabilities)
        ]
    elif event_type == "step_update":
        data = payload.get("data") or {}
        steps = state.setdefault("execution_steps", [])
        current_step = int(data.get("current_step") or 0) - 1
        if 0 <= current_step < len(steps):
            for i in range(current_step):
                if steps[i].get("status") != "completed":
                    steps[i]["status"] = "completed"
            steps[current_step]["status"] = "running"
            steps[current_step]["description"] = data.get("thinking") or "执行中..."
        if data.get("thinking"):
            _set_thinking(state, data["thinking"])
        if data.get("references"):
            state["references"] = data["references"]
    elif event_type == "workflow_complete":
        for step in state.get("execution_steps") or []:
            step["status"] = "completed"
        data = payload.get("data") or {}
        if data.get("references"):
            state["references"] = data["references"]
        _set_thinking(state, "✓ 执行完成")
    elif event_type == "error":
        message = payload.get("message") or "执行失败"
        _set_thinking(state, f"✗ 错误: {message}")
        state["content"] = f"{state.get('content', '')}\n\n**错误**: {message}".strip()


def _parse_sse_payload(event: str) -> dict[str, Any] | None:
    """从单个 SSE 字符串中取 JSON payload；[DONE] 或非 JSON 返回 None。"""
    for line in event.splitlines():
        if not line.startswith("data: "):
            continue
        data_str = line.removeprefix("data: ").strip()
        if not data_str or data_str == "[DONE]":
            return None
        try:
            return json.loads(data_str)
        except json.JSONDecodeError:
            logger.debug("忽略无法解析的 SSE: %s", data_str)
            return None
    return None


@router.post("/upload")
async def upload_chat_file(
    raw_request: Request,
    file: UploadFile = File(...),
    session_id: str = Form(..., description="会话 ID，文件将隔离写入 session 工作区"),
    user_id: str = Depends(get_current_user_id),
):
    """上传聊天附件到指定会话工作区。

    支持常见文档、文本/日志、表格、代码、图片和压缩包，最大 20 MB。文件写入
    `.eido/workspaces/<session_id>/uploads/`，
    返回的绝对路径供 agent 读取。
    """
    session_token = set_session_id(session_id)
    raw_request.state.session_id = session_id
    try:
        try:
            validate_session_id(session_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        if get_chat_session_store().get_session(user_id, session_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")

        ext = Path(file.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"不支持 {ext or '无扩展名'} 格式。" f"当前支持: {supported_extensions_label()}"
                ),
            )
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail="文件大小超过 20 MB 限制")

        ws = get_session_workspace_manager()
        upload_dir = ws.uploads_dir(session_id)
        safe_name = f"{uuid.uuid4().hex[:8]}_{Path(file.filename or 'file').name}"
        out_path = upload_dir / safe_name
        out_path.write_bytes(content)
        abs_path = str(out_path.resolve())
        logger.info(f"[{user_id}][session={session_id}] 上传文件: {file.filename} -> {abs_path}")
        return {"path": abs_path, "name": file.filename or safe_name}
    finally:
        reset_session_id(session_token)


@router.post("/chat")
async def chat_completion(
    request: ChatRequest,
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """统一聊天入口：根据 AGENT_HARNESS 配置选择执行后端，流式返回。

    要求请求体携带 session_id，agent cwd 会切到对应 session 工作区。
    """
    execution_guard = None
    stream_owns_guard = False
    request_session_token = None
    try:
        if not request.messages:
            raise HTTPException(status_code=400, detail="消息列表为空")
        if not request.session_id:
            raise HTTPException(status_code=400, detail="缺少 session_id")
        try:
            validate_session_id(request.session_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        request_session_token = set_session_id(request.session_id)
        raw_request.state.session_id = request.session_id

        harness_type = (
            request.harness or ""
        ).strip().lower() or settings.AGENT_HARNESS.strip().lower()

        if harness_type == "opencode":
            from app.services.open_code_service import get_open_code_service

            svc = get_open_code_service()
        elif harness_type == "claude_code":
            from app.services.claude_skill_service import get_claude_skill_service

            svc = get_claude_skill_service()
        else:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的 AI 后端: {harness_type}（可选: claude_code, opencode）",
            )

        if svc is None:
            raise HTTPException(status_code=503, detail=f"技能服务未初始化（{harness_type}）")

        logger.info(
            f"[{user_id}][session={request.session_id}] 收到聊天请求 - harness={harness_type} - 消息数: {len(request.messages)}"
            + (f" [含流水线上下文 {len(request.context)} 字符]" if request.context else "")
        )

        store = get_chat_session_store()
        session = store.get_session(user_id, request.session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")

        guard = get_chat_execution_guard()
        locked_project_id = session.get("project_id")
        if not guard.try_acquire(request.session_id, project_id=locked_project_id):
            raise HTTPException(
                status_code=409,
                detail="该会话正在执行或所属项目正在变更，请稍后重试",
            )
        execution_guard = guard

        # session 快照是在 guard 之外读取的。加锁后重新读取，确保我们持有的
        # Project 共享租约与数据库中的当前归属完全一致；移动/删除若抢先完成，
        # 本次请求返回 409，由客户端按新归属重试。
        locked_session = store.get_session(user_id, request.session_id)
        if locked_session is None:
            raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")
        if locked_session.get("project_id") != locked_project_id:
            raise HTTPException(status_code=409, detail="会话所属项目已变化，请重试")

        # Project 只能由已验证归属的 session 推导，避免 session/project 组合越权。
        project_context = load_project_context(user_id, request.session_id)
        if (
            project_context
            and project_context.applied_context_revision != project_context.context_revision
        ):
            # Revision 变化后 provider 记忆可能仍含旧项目资料。
            # 先驱逐内存 engine，再原子清理 provider SID 并绑定本次快照。
            try:
                from app.services.claude_skill_service import get_claude_skill_service

                claude_service = get_claude_skill_service()
                if claude_service is not None:
                    claude_service.reset_session(request.session_id)
            except Exception as exc:
                logger.error(
                    "刷新项目上下文缓存失败 session=%s: %s",
                    request.session_id,
                    exc,
                    exc_info=True,
                )
                raise HTTPException(status_code=503, detail="项目上下文刷新失败，请重试") from exc

            prepared = store.prepare_project_context(
                user_id,
                request.session_id,
                project_context.id,
                project_context.context_revision,
            )
            if prepared is None:
                raise HTTPException(status_code=409, detail="项目上下文已变化，请重试")

        # 归属校验通过后再确保 session 工作区目录已创建
        get_session_workspace_manager().session_root(request.session_id)

        latest = request.messages[-1]
        if latest.role == "user":
            store.append_message(
                user_id,
                request.session_id,
                message_id=latest.id,
                role="user",
                content=latest.content,
                extra={},
            )
        # 原生 provider 会话可能因 Project 移动/更新而重建。始终从服务端持久化
        # 历史构造执行输入，避免信任客户端伪造历史，也能在重建时恢复上下文。
        execution_messages = [
            ChatMessage(id=item["id"], role=item["role"], content=item["content"])
            for item in store.list_messages(request.session_id, user_id=user_id, limit=80)
        ]

        async def stream_with_persistence():
            stream_session_token = set_session_id(request.session_id)
            state: dict[str, Any] = {"content": ""}
            assistant_message_id = request.assistant_message_id or uuid.uuid4().hex[:12]
            try:
                async for event in svc.execute_stream(
                    execution_messages,
                    request.context,
                    user_id=user_id,
                    session_id=request.session_id,
                    project_context=project_context,
                ):
                    payload = _parse_sse_payload(event)
                    if payload:
                        _accumulate_sse_event(state, payload)
                    yield event
            except Exception as e:
                logger.error(f"流式执行异常，准备保存 assistant 错误状态: {e}", exc_info=True)
                _set_thinking(state, f"✗ 执行失败: {e}")
                state["content"] = f"{state.get('content', '')}\n\n**错误**: {e}".strip()
                raise
            finally:
                content = (state.get("content") or "").strip()
                thinking = (state.get("thinking") or "").strip()
                if content or thinking:
                    try:
                        store.append_message(
                            user_id,
                            request.session_id,
                            message_id=assistant_message_id,
                            role="assistant",
                            content=content,
                            extra=_message_extra_from_stream_state(state),
                        )
                        logger.info(
                            f"[{user_id}][session={request.session_id}] assistant 消息已由后端保存: {assistant_message_id}"
                        )
                    except Exception as e:
                        logger.error(f"保存 assistant 消息失败: {e}", exc_info=True)
                try:
                    execution_guard.release(request.session_id)
                    from app.services.chat_execution_queue import get_chat_execution_queue

                    get_chat_execution_queue().kick(user_id, request.session_id)
                finally:
                    reset_session_id(stream_session_token)

        response = StreamingResponse(stream_with_persistence(), media_type="text/event-stream")
        stream_owns_guard = True
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"聊天处理异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e
    finally:
        if execution_guard is not None and not stream_owns_guard:
            execution_guard.release(request.session_id)
            try:
                from app.services.chat_execution_queue import get_chat_execution_queue

                get_chat_execution_queue().kick(user_id, request.session_id)
            except Exception:
                logger.exception("恢复会话队列失败 session=%s", request.session_id)
        if request_session_token is not None:
            reset_session_id(request_session_token)


@router.post("/control")
async def control_active_chat(
    request: ChatControlRequest,
    user_id: str = Depends(get_current_user_id),
):
    """Queue another turn or inject a Steer message into an active Claude turn."""
    message_id = request.message.id or uuid.uuid4().hex[:12]
    try:
        validate_session_id(request.session_id)
        validate_session_id(message_id)
        validate_session_id(request.assistant_message_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    store = get_chat_session_store()
    if request.message.role != "user":
        raise HTTPException(status_code=400, detail="执行中追加内容必须是 user 消息")
    content = request.message.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息内容为空")

    session_id = request.session_id
    session = store.get_session(user_id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")

    harness = (request.harness or settings.AGENT_HARNESS).strip().lower()
    if harness not in {"claude_code", "opencode"}:
        raise HTTPException(status_code=400, detail=f"不支持的 AI 后端: {harness}")
    guard = get_chat_execution_guard()
    active = guard.is_active(session_id)

    if request.mode == "steer":
        if not active:
            raise HTTPException(status_code=409, detail="该会话当前没有可调整的执行")
        from app.services.claude_skill_service import get_claude_skill_service

        service = get_claude_skill_service()
        if service is None:
            raise HTTPException(status_code=503, detail="Claude Code 服务未初始化")
        from app.services.chat_execution_queue import get_chat_execution_queue

        # Promotion must take the row atomically before the active turn can
        # finish and kick the queue, otherwise the same instruction could be
        # injected and then run again as a normal queued turn.
        queue = get_chat_execution_queue()
        promoted_run = queue.take(user_id, session_id, message_id)
        try:
            steered = await service.steer_session(user_id, session_id, content)
        except Exception:
            if promoted_run is not None:
                queue.enqueue(promoted_run, front=True)
            raise
        if not steered:
            if promoted_run is not None:
                queue.enqueue(promoted_run, front=True)
            raise HTTPException(status_code=409, detail="当前执行尚未进入可 Steer 阶段，请改用排队")

        store.append_message(
            user_id,
            session_id,
            message_id=message_id,
            role="user",
            content=content,
            extra={"deliveryMode": "steer", "deliveryStatus": "applied"},
        )
        return {"ok": True, "mode": "steer", "status": "applied"}

    from app.services.chat_execution_queue import QueuedChatRun, get_chat_execution_queue

    queue = get_chat_execution_queue()
    position = queue.enqueue(
        QueuedChatRun(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
            content=content,
            assistant_message_id=request.assistant_message_id,
            harness=harness,
            context=request.context,
        ),
    )
    return {"ok": True, "mode": "queue", "status": "queued", "position": position}


@router.get("/queue/{session_id}")
async def get_chat_queue(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        validate_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if get_chat_session_store().get_session(user_id, session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")
    from app.services.chat_execution_queue import get_chat_execution_queue

    items = get_chat_execution_queue().pending(user_id, session_id)
    active = get_chat_execution_guard().is_active(session_id)
    steer_available = False
    if active:
        from app.services.claude_skill_service import get_claude_skill_service

        service = get_claude_skill_service()
        steer_available = bool(
            service is not None and service.can_steer_session(user_id, session_id)
        )
    return {
        "active": active,
        "steer_available": steer_available,
        "count": len(items),
        "items": items,
    }


@router.delete("/queue/{session_id}/{message_id}")
async def delete_queued_chat_message(
    session_id: str,
    message_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """Delete a pending follow-up before its execution starts."""
    try:
        validate_session_id(session_id)
        validate_session_id(message_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if get_chat_session_store().get_session(user_id, session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")
    from app.services.chat_execution_queue import get_chat_execution_queue

    if not get_chat_execution_queue().remove(user_id, session_id, message_id):
        raise HTTPException(status_code=409, detail="消息已开始执行或已不在队列中")
    return {"ok": True}


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "chat"}
