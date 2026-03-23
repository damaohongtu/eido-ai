"""
Chat endpoint：通过 claude_agent_sdk 自动规划执行技能
"""
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.core.auth import get_current_user_id
from app.core.config import settings
from app.schemas.chat import ChatRequest, ChatResponse, ErrorResponse
from app.services.claude_skill_service import get_claude_skill_service

router = APIRouter()
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {".md", ".pdf"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


@router.post("/upload")
async def upload_chat_file(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """上传聊天附件，支持 .md 和 .pdf，最大 20 MB。返回工作区内的绝对路径供 agent 读取。"""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 .md 和 .pdf 格式，当前: {ext or '无扩展名'}"
        )
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 20 MB 限制")
    upload_dir = Path(settings.WORKSPACE_ROOT) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:8]}_{Path(file.filename or 'file').name}"
    out_path = upload_dir / safe_name
    out_path.write_bytes(content)
    abs_path = str(out_path.resolve())
    logger.info(f"[{user_id}] 上传文件: {file.filename} -> {abs_path}")
    return {"path": abs_path, "name": file.filename or safe_name}


@router.post("/chat")
async def chat_completion(
    request: ChatRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    统一聊天入口：通过 claude_agent_sdk 自动从用户输入中识别并执行相关技能，流式返回。
    """
    try:
        if not request.messages:
            raise HTTPException(status_code=400, detail="消息列表为空")

        svc = get_claude_skill_service()
        if svc is None:
            raise HTTPException(status_code=503, detail="技能服务未初始化")

        logger.info(
            f"[{user_id}] 收到聊天请求 - 消息数: {len(request.messages)}"
            + (f" [含流水线上下文 {len(request.context)} 字符]" if request.context else "")
        )

        return StreamingResponse(
            svc.execute_stream(request.messages, request.context, user_id=user_id),
            media_type="text/event-stream",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"聊天处理异常: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "chat"}
