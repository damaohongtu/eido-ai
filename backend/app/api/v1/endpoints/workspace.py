"""
工作区文件服务：供聊天中生成的图片（如 K 线图）在前端预览。

- 不传 session_id 时：兼容历史路径，在 WORKSPACE_ROOT 全局范围内解析（仅限只读预览/下载）
- 传 session_id 时：根收窄到 `.eido/workspaces/<session_id>/`，杜绝跨会话窥探
"""
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.auth import get_current_user_id
from app.core.config import settings
from app.services.chat_session_store import get_chat_session_store
from app.services.session_workspace import (
    get_session_workspace_manager,
    validate_session_id,
)

router = APIRouter()
logger = logging.getLogger(__name__)

WORKSPACE_ROOT = Path(settings.WORKSPACE_ROOT).resolve()
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def _resolve_global_path(path_str: str) -> Path:
    """全局范围内解析路径（兼容旧路径），确保在 WORKSPACE_ROOT 内。"""
    path = Path(path_str)
    resolved = (path if path.is_absolute() else WORKSPACE_ROOT / path_str).resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径不在工作区范围内")
    return resolved


def _resolve_session_path(session_id: str, path_str: str) -> Path:
    """限定在 session 工作区内解析路径。"""
    try:
        validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        return get_session_workspace_manager().safe_resolve(session_id, path_str)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/file")
async def get_workspace_file(
    path: str = Query(..., description="文件路径，绝对或相对均可"),
    download: bool = Query(False, description="是否以附件形式下载"),
    filename: str | None = Query(None, description="下载时使用的文件名"),
    session_id: str | None = Query(None, description="会话 ID。传入后路径解析将收窄到该会话工作区"),
    user_id: str = Depends(get_current_user_id),
):
    """获取工作区/会话工作区内的文件，用于聊天中生成图片预览或文件下载。"""
    try:
        if session_id:
            if get_chat_session_store().get_session(user_id, session_id) is None:
                raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")
            resolved = _resolve_session_path(session_id, path)
        else:
            resolved = _resolve_global_path(path)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"无效路径: {path} - {e}")
        raise HTTPException(status_code=400, detail="无效的文件路径")

    if not resolved.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    if not resolved.is_file():
        raise HTTPException(status_code=400, detail="不是文件")

    ext = resolved.suffix.lower()
    media_type = None
    if ext in ALLOWED_IMAGE_EXT:
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".svg": "image/svg+xml",
        }
        media_type = media_types.get(ext)

    download_name = filename or resolved.name
    return FileResponse(
        resolved,
        media_type=media_type,
        filename=download_name,
        content_disposition_type="attachment" if download else "inline",
    )
