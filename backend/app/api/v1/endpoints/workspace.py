"""
工作区文件服务：供聊天中生成的图片（如 K 线图）在前端预览。

- 不传 session_id 时：仅兼容历史 uploads/output/outputs 目录的只读预览/下载
- 传 session_id 时：根收窄到 `.eido/workspaces/<session_id>/`，杜绝跨会话窥探
"""
import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.auth import get_current_user_id
from app.core.config import settings
from app.services.chat_execution_guard import get_chat_execution_guard
from app.services.chat_session_store import get_chat_session_store
from app.services.file_preview import (
    file_content_disposition,
    file_response_security_headers,
)
from app.services.session_workspace import (
    get_session_workspace_manager,
    validate_session_id,
)

router = APIRouter()
logger = logging.getLogger(__name__)

WORKSPACE_ROOT = Path(settings.WORKSPACE_ROOT).resolve()
DATA_ROOT = settings.data_root.resolve()
LEGACY_FILE_ROOTS = tuple(
    (WORKSPACE_ROOT / name).resolve() for name in ("uploads", "output", "outputs")
)
FORCE_ATTACHMENT_EXT = {
    ".html",
    ".htm",
    ".xhtml",
    ".svg",
    ".xml",
    ".mhtml",
    ".mht",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
}


def _content_disposition_type(
    ext: str,
    download: bool,
    preview: bool = False,
    media_type: str | None = None,
) -> str:
    """Render active content inline only for an explicit sandboxed preview."""
    return file_content_disposition(
        ext,
        download=download,
        preview=preview,
        force_attachment_extensions=FORCE_ATTACHMENT_EXT,
        media_type=media_type,
    )


def _resolve_global_path(path_str: str) -> Path:
    """解析旧文件路径，但拒绝读取源码、配置和其它仓库文件。"""
    path = Path(path_str)
    resolved = (path if path.is_absolute() else WORKSPACE_ROOT / path_str).resolve()
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径不在工作区范围内")
    # 历史兼容分支绝不能暴露数据库、项目资料或其它 Eido 持久化数据。
    try:
        resolved.relative_to(DATA_ROOT)
    except ValueError:
        pass
    else:
        raise HTTPException(status_code=403, detail="持久化数据必须通过受归属校验的接口访问")
    if not any(
        resolved == root or root in resolved.parents for root in LEGACY_FILE_ROOTS
    ):
        raise HTTPException(status_code=403, detail="旧路径仅允许访问 uploads/output/outputs")
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
    preview: bool = Query(False, description="是否使用受限浏览器预览"),
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
    # Starlette otherwise guesses from ``filename``.  That value is only a
    # Content-Disposition display name and must never be able to turn a safe
    # file such as report.txt into an inline text/html response.
    media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"

    download_name = filename or resolved.name
    return FileResponse(
        resolved,
        media_type=media_type,
        filename=download_name,
        content_disposition_type=_content_disposition_type(
            ext, download, preview, media_type
        ),
        headers=file_response_security_headers(
            ext, download=download, preview=preview, media_type=media_type
        ),
    )


@router.get("/files")
async def list_workspace_files(
    session_id: str = Query(..., description="会话 ID"),
    user_id: str = Depends(get_current_user_id),
):
    try:
        validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if get_chat_session_store().get_session(user_id, session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")
    mgr = get_session_workspace_manager()
    nodes = mgr.list_directory(session_id)
    return {"files": [n.to_dict() for n in nodes]}


@router.delete("/file")
async def delete_workspace_file(
    path: str = Query(..., description="文件路径"),
    session_id: str = Query(..., description="会话 ID"),
    user_id: str = Depends(get_current_user_id),
):
    try:
        validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    store = get_chat_session_store()
    if store.get_session(user_id, session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")
    guard = get_chat_execution_guard()
    if not guard.try_acquire(session_id):
        raise HTTPException(status_code=409, detail="会话正在执行或变更，暂时不能删除文件")
    try:
        # The ownership check precedes the process-local guard so foreign session
        # IDs cannot be used for contention. Recheck after acquisition to cover a
        # concurrent session deletion between the first check and the guard.
        if store.get_session(user_id, session_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")
        mgr = get_session_workspace_manager()
        deleted = mgr.delete_file(session_id, path)
    except ValueError as e:
        raise HTTPException(status_code=403, detail=str(e))
    finally:
        guard.release(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="文件不存在")
    return {"deleted": True}
