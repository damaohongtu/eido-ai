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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.core.auth import get_current_user_id
from app.core.config import settings
from app.schemas.chat import ChatRequest
from app.services.chat_session_store import get_chat_session_store
from app.services.session_workspace import (
    get_session_workspace_manager,
    validate_session_id,
)

router = APIRouter()
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".md", ".pdf", ".csv", ".xls", ".xlsx"}
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
            logger.debug(f"忽略无法解析的 SSE: {data_str[:120]}")
            return None
    return None


@router.post("/upload")
async def upload_chat_file(
    file: UploadFile = File(...),
    session_id: str = Form(..., description="会话 ID，文件将隔离写入 session 工作区"),
    user_id: str = Depends(get_current_user_id),
):
    """上传聊天附件到指定会话工作区。

    支持 .md/.pdf/.csv/.xls/.xlsx，最大 20 MB。文件写入 `.eido/workspaces/<session_id>/uploads/`，
    返回的绝对路径供 agent 读取。
    """
    try:
        validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if get_chat_session_store().get_session(user_id, session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")

    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 .md/.pdf/.csv/.xls/.xlsx 格式，当前: {ext or '无扩展名'}"
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


@router.post("/chat")
async def chat_completion(
    request: ChatRequest,
    user_id: str = Depends(get_current_user_id),
):
    """统一聊天入口：根据 AGENT_HARNESS 配置选择执行后端，流式返回。

    要求请求体携带 session_id，agent cwd 会切到对应 session 工作区。
    """
    try:
        if not request.messages:
            raise HTTPException(status_code=400, detail="消息列表为空")
        if not request.session_id:
            raise HTTPException(status_code=400, detail="缺少 session_id")
        try:
            validate_session_id(request.session_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        harness_type = settings.AGENT_HARNESS.strip().lower()

        if harness_type == "open_harness":
            from app.services.open_harness_service import get_open_harness_service
            svc = get_open_harness_service()
        else:
            from app.services.claude_skill_service import get_claude_skill_service
            svc = get_claude_skill_service()

        if svc is None:
            raise HTTPException(status_code=503, detail=f"技能服务未初始化（{harness_type}）")

        logger.info(
            f"[{user_id}][session={request.session_id}] 收到聊天请求 - harness={harness_type} - 消息数: {len(request.messages)}"
            + (f" [含流水线上下文 {len(request.context)} 字符]" if request.context else "")
        )

        store = get_chat_session_store()
        if store.get_session(user_id, request.session_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")

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

        async def stream_with_persistence():
            state: dict[str, Any] = {"content": ""}
            assistant_message_id = request.assistant_message_id or uuid.uuid4().hex[:12]
            try:
                async for event in svc.execute_stream(
                    request.messages,
                    request.context,
                    user_id=user_id,
                    session_id=request.session_id,
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

        return StreamingResponse(stream_with_persistence(), media_type="text/event-stream")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"聊天处理异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "chat"}
