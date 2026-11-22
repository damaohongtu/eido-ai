"""HTTP endpoints for chat, files and turn control."""

import json
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import aclosing
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from app.core.auth import get_current_user_id
from app.core.logging_context import reset_session_id, set_session_id
from app.schemas.chat import ChatCompletionRequest, ChatControlRequest, ChatRequest
from app.services.chat.events import ChatEvent, StreamSignal
from app.services.chat.execution_guard import get_chat_execution_guard
from app.services.chat.session_store import get_chat_session_store
from app.services.chat.session_workspace import (
    get_session_workspace_manager,
    validate_session_id,
)
from app.services.chat.turn import ChatTurn, ChatTurnRejected, prepare_chat_turn, resolve_chat_model
from app.services.claude.execution_profile import resolve_runtime_mode
from app.services.claude.models import load_model_catalog
from app.services.files.supported_types import (
    SUPPORTED_FILE_EXTENSIONS,
    supported_extensions_label,
)

router = APIRouter()
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = SUPPORTED_FILE_EXTENSIONS
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


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


async def _sse(events: AsyncGenerator[ChatEvent, None]) -> AsyncGenerator[str, None]:
    async with aclosing(events):
        async for event in events:
            if event is StreamSignal.HEARTBEAT:
                yield ": ping\n\n"
            elif event is StreamSignal.DONE:
                yield "data: [DONE]\n\n"
            else:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


class _ChatResponse(StreamingResponse):
    def __init__(self, turn: ChatTurn):
        self.turn = turn
        super().__init__(_sse(turn.events()), media_type="text/event-stream")

    async def stream_response(self, send: Send) -> None:
        async with aclosing(self.body_iterator):
            await super().stream_response(send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.turn.close()


@router.post("/chat")
async def chat_completion(
    request: ChatRequest,
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    return _complete_chat(request, raw_request, user_id)


@router.post("/completions")
async def create_chat_completion(
    request: ChatCompletionRequest,
    raw_request: Request,
    user_id: str = Depends(get_current_user_id),
):
    """Create a missing session and stream a chat turn."""
    return _complete_chat(request, raw_request, user_id, create_session=True)


def _complete_chat(
    request: ChatRequest, raw_request: Request, user_id: str, *, create_session: bool = False
):
    if not request.session_id:
        raise HTTPException(status_code=400, detail="缺少 session_id")
    try:
        validate_session_id(request.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    raw_request.state.session_id = request.session_id
    token = set_session_id(request.session_id)
    try:
        turn = prepare_chat_turn(user_id, request, create_session=create_session)
    except ChatTurnRejected as exc:
        status = {"input": 400, "not_found": 404, "conflict": 409, "unavailable": 503}
        raise HTTPException(status_code=status[exc.reason], detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("聊天处理异常")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        reset_session_id(token)
    response = _ChatResponse(turn)
    response.headers["X-Session-Id"] = turn.session_id
    return response


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

    try:
        model = resolve_chat_model(request.model or session.get("model"))
    except ChatTurnRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime_mode = resolve_runtime_mode(
        request.runtime_mode or session.get("runtime_mode"), default="agent"
    )
    if request.runtime_mode and request.runtime_mode != session.get("runtime_mode", "agent"):
        raise HTTPException(status_code=409, detail="会话模式已变化，请刷新后重试")
    guard = get_chat_execution_guard()
    active = guard.is_active(session_id)

    if request.mode == "steer":
        if not active:
            raise HTTPException(status_code=409, detail="该会话当前没有可调整的执行")
        from app.services.claude.runtime import get_claude_runtime

        service = get_claude_runtime()
        if service is None:
            raise HTTPException(status_code=503, detail="Claude Code 服务未初始化")
        from app.services.chat.execution_queue import get_chat_execution_queue

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

    from app.services.chat.execution_queue import QueuedChatRun, get_chat_execution_queue

    queue = get_chat_execution_queue()
    position = queue.enqueue(
        QueuedChatRun(
            user_id=user_id,
            session_id=session_id,
            message_id=message_id,
            content=content,
            assistant_message_id=request.assistant_message_id,
            model=model,
            runtime_mode=runtime_mode,
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
    from app.services.chat.execution_queue import get_chat_execution_queue

    items = get_chat_execution_queue().pending(user_id, session_id)
    active = get_chat_execution_guard().is_active(session_id)
    steer_available = False
    if active:
        from app.services.claude.runtime import get_claude_runtime

        service = get_claude_runtime()
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
    from app.services.chat.execution_queue import get_chat_execution_queue

    if not get_chat_execution_queue().remove(user_id, session_id, message_id):
        raise HTTPException(status_code=409, detail="消息已开始执行或已不在队列中")
    return {"ok": True}


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "chat"}


@router.get("/models")
async def list_models(user_id: str = Depends(get_current_user_id)):
    try:
        return load_model_catalog().public()
    except (OSError, ValueError) as exc:
        logger.exception("读取模型配置失败")
        raise HTTPException(status_code=500, detail=f"模型配置无效: {exc}") from exc
