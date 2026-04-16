"""
工作区文件服务：供聊天中生成的图片（如 K 线图）在前端预览。
"""
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.core.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

WORKSPACE_ROOT = Path(settings.WORKSPACE_ROOT)
ALLOWED_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def _resolve_safe_path(path_str: str) -> Path:
    """解析路径并确保在工作区范围内，防止路径遍历攻击。"""
    path = Path(path_str)
    if not path.is_absolute():
        path = (WORKSPACE_ROOT / path_str).resolve()
    else:
        path = path.resolve()
    try:
        path.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise HTTPException(status_code=403, detail="路径不在工作区范围内")
    return path


@router.get("/file")
async def get_workspace_file(
    path: str = Query(..., description="工作区内文件路径，支持绝对或相对路径"),
    download: bool = Query(False, description="是否以附件形式下载"),
    filename: str | None = Query(None, description="下载时使用的文件名"),
):
    """
    获取工作区内的文件内容，用于聊天中生成的图片预览。
    支持绝对路径（如 /Users/.../workspace/chart.png）或相对路径（如 workspace/chart.png）。
    """
    try:
        resolved = _resolve_safe_path(path)
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
