"""Personal Project CRUD and shared-file endpoints."""
from __future__ import annotations

import hashlib
import logging
import os
import unicodedata
import uuid
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from python_multipart.exceptions import MultipartParseError
from pydantic import BaseModel, Field
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.auth import get_current_user_id
from app.services.chat_execution_guard import get_chat_execution_guard
from app.services.chat_session_store import (
    ProjectQuotaExceededError,
    get_chat_session_store,
)
from app.services.project_workspace import (
    PROJECT_FILE_EXTENSIONS,
    get_project_workspace_manager,
    validate_project_file_id,
    validate_project_id,
)
from app.services.session_workspace import get_session_workspace_manager, validate_session_id

router = APIRouter()
logger = logging.getLogger(__name__)

MEDIA_TYPES_BY_EXTENSION = {
    ".md": "text/markdown; charset=utf-8",
    ".pdf": "application/pdf",
    ".csv": "text/csv; charset=utf-8",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
# Active same-origin content and Office documents are never rendered inline.  This
# prevents a generated HTML/SVG file from becoming script-capable Project content,
# and keeps browser handling of Office formats deterministic.
FORCE_ATTACHMENT_EXTENSIONS = {
    ".html",
    ".htm",
    ".svg",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
}
MAX_PROJECT_FILE_SIZE = 20 * 1024 * 1024
_CHUNK_SIZE = 1024 * 1024


class _LeaseFileResponse(FileResponse):
    """Always release a Project lease, including Range errors and disconnects."""

    def __init__(self, *args, release_lease: Callable[[], None], **kwargs):
        super().__init__(*args, **kwargs)
        self._release_lease = release_lease
        self._lease_released = False

    async def __call__(self, scope, receive, send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            if not self._lease_released:
                self._lease_released = True
                self._release_lease()


class _LimitedMultipartParser(MultiPartParser):
    """Enforce the current Project byte budget while multipart is being parsed."""

    def __init__(self, *args, max_file_size: int, **kwargs):
        super().__init__(*args, **kwargs)
        self._max_file_size = max(0, int(max_file_size))
        self._current_file_size = 0

    def on_part_begin(self) -> None:
        super().on_part_begin()
        self._current_file_size = 0

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        if self._current_part.file is not None:
            self._current_file_size += end - start
            if self._current_file_size > self._max_file_size:
                raise MultiPartException(
                    "文件大小超过单文件限制或当前剩余配额"
                )
        super().on_part_data(data, start, end)


class CreateProjectRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field("", max_length=2000)
    instructions: str = Field("", max_length=20000)


class PatchProjectRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    description: Optional[str] = Field(None, max_length=2000)
    instructions: Optional[str] = Field(None, max_length=20000)
    archived: Optional[bool] = None


class ImportProjectFileRequest(BaseModel):
    session_id: str
    path: str
    display_name: Optional[str] = Field(None, max_length=255)


def _validate_project_id_or_400(project_id: str) -> None:
    try:
        validate_project_id(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _validate_file_id_or_400(file_id: str) -> None:
    try:
        validate_project_file_id(file_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_project(user_id: str, project_id: str, *, active: bool = False) -> dict:
    _validate_project_id_or_400(project_id)
    project = get_chat_session_store().get_project(user_id, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if active and project.get("archived_at"):
        raise HTTPException(status_code=409, detail="项目已归档，不能新增会话或资料")
    return project


def _safe_display_name(name: str) -> str:
    value = Path((name or "file").replace("\\", "/")).name.strip()
    value = "".join(
        "_" if unicodedata.category(char).startswith("C") else char for char in value
    ).replace("`", "'")
    return value[:255] or "file"


def _validate_extension(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext not in PROJECT_FILE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"仅支持 {', '.join(sorted(PROJECT_FILE_EXTENSIONS))} 格式",
        )
    return ext


def _max_file_size_for_capacity(capacity: dict[str, int]) -> int:
    if capacity["project_remaining_files"] <= 0:
        raise HTTPException(status_code=413, detail="项目共享资料数量已达上限")
    if capacity["project_remaining_bytes"] <= 0:
        raise HTTPException(status_code=413, detail="项目共享资料总容量已达上限")
    if capacity["user_remaining_files"] <= 0:
        raise HTTPException(status_code=413, detail="当前用户的项目资料数量已达上限")
    if capacity["user_remaining_bytes"] <= 0:
        raise HTTPException(status_code=413, detail="当前用户的项目资料总容量已达上限")
    return min(MAX_PROJECT_FILE_SIZE, capacity["remaining_bytes"])


async def _parse_single_upload(
    request: Request, *, max_file_size: int
) -> tuple[FormData, UploadFile]:
    content_type = request.headers.get("content-type", "")
    if content_type.partition(";")[0].strip().lower() != "multipart/form-data":
        raise HTTPException(
            status_code=400,
            detail="Content-Type 必须为 multipart/form-data",
        )
    parser = _LimitedMultipartParser(
        request.headers,
        request.stream(),
        max_files=1,
        max_fields=4,
        max_file_size=max_file_size,
    )
    try:
        form = await parser.parse()
    except (MultiPartException, MultipartParseError, KeyError) as exc:
        # Starlette closes these for MultiPartException, but python-multipart can
        # raise MultipartParseError directly after a temporary file was opened.
        for temporary_file in parser._files_to_close_on_error:
            temporary_file.close()
        status = 413 if "文件大小超过" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        await form.close()
        raise HTTPException(status_code=400, detail="缺少 file 文件字段")
    return form, upload


async def _stream_upload(
    upload: UploadFile, destination: Path, *, max_size: int
) -> tuple[int, str]:
    """Write an upload atomically while enforcing size before it reaches disk in full."""
    temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.upload")
    digest = hashlib.sha256()
    size = 0
    try:
        with temp.open("wb") as handle:
            while chunk := await upload.read(_CHUNK_SIZE):
                size += len(chunk)
                if size > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail="文件大小超过单文件限制或当前剩余配额",
                    )
                digest.update(chunk)
                handle.write(chunk)
        os.replace(temp, destination)
        return size, digest.hexdigest()
    finally:
        temp.unlink(missing_ok=True)


def _discard_uncommitted_file(
    user_id: str, project_id: str, storage_name: str, destination: Path
) -> None:
    """Remove a file whose metadata transaction failed, durably queueing retries."""
    store = get_chat_session_store()
    # A commit can succeed even if a post-commit connection error reaches the
    # caller. Never remove an active file until metadata absence is confirmed.
    if store.project_file_resource_exists(project_id, storage_name):
        return
    size_bytes = 0
    if not destination.is_symlink() and destination.is_file():
        size_bytes = destination.stat().st_size
    try:
        destination.unlink(missing_ok=True)
    except Exception as exc:
        logger.exception(
            "清理未提交项目文件失败，已加入重试队列 project=%s storage=%s",
            project_id,
            storage_name,
        )
        try:
            store.enqueue_storage_cleanup(
                resource_type="file",
                project_id=project_id,
                storage_name=storage_name,
                user_id=user_id,
                file_count=1,
                size_bytes=size_bytes,
            )
        except Exception:
            logger.exception(
                "登记项目文件清理任务失败 project=%s storage=%s error=%s",
                project_id,
                storage_name,
                exc,
            )


def _copy_file(source: Path, destination: Path, *, max_size: int) -> tuple[int, str]:
    if source.stat().st_size > max_size:
        raise HTTPException(
            status_code=413, detail="文件大小超过单文件限制或当前剩余配额"
        )
    temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.import")
    digest = hashlib.sha256()
    size = 0
    try:
        with source.open("rb") as reader, temp.open("wb") as writer:
            while chunk := reader.read(_CHUNK_SIZE):
                size += len(chunk)
                if size > max_size:
                    raise HTTPException(
                        status_code=413,
                        detail="文件大小超过单文件限制或当前剩余配额",
                    )
                digest.update(chunk)
                writer.write(chunk)
        os.replace(temp, destination)
        return size, digest.hexdigest()
    finally:
        temp.unlink(missing_ok=True)


def _resolve_generated_output(session_id: str, path: str) -> Path:
    """Resolve a promotable result, restricted to the session's outputs tree.

    ``safe_resolve`` first enforces the Session Workspace boundary.  Comparing
    the fully resolved result to the fully resolved outputs directory also
    rejects an ``outputs/...`` symlink that points at uploads or elsewhere.
    Absolute paths emitted by an agent remain supported when they are inside
    this exact session's outputs directory.
    """
    manager = get_session_workspace_manager()
    try:
        source = manager.safe_resolve(session_id, path)
        outputs_root = manager.outputs_dir(session_id).resolve()
        source.relative_to(outputs_root)
    except ValueError as exc:
        raise HTTPException(
            status_code=403,
            detail="仅允许将来源会话 outputs 目录中的生成产物保存为项目资料",
        ) from exc
    return source


@router.get("/")
async def list_projects(
    include_archived: bool = Query(False),
    user_id: str = Depends(get_current_user_id),
):
    return get_chat_session_store().list_projects(user_id, include_archived=include_archived)


@router.post("/")
async def create_project(
    body: CreateProjectRequest,
    user_id: str = Depends(get_current_user_id),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="项目名称不能为空")
    project = get_chat_session_store().create_project(
        user_id,
        name=name,
        description=body.description.strip(),
        instructions=body.instructions.strip(),
    )
    return project


@router.get("/{project_id}")
async def get_project(project_id: str, user_id: str = Depends(get_current_user_id)):
    return _require_project(user_id, project_id)


@router.patch("/{project_id}")
async def patch_project(
    project_id: str,
    body: PatchProjectRequest,
    user_id: str = Depends(get_current_user_id),
):
    _require_project(user_id, project_id)
    fields = body.model_dump(exclude_unset=True)
    if "name" in fields:
        if fields["name"] is None:
            raise HTTPException(status_code=400, detail="项目名称不能为空")
        fields["name"] = fields["name"].strip()
        if not fields["name"]:
            raise HTTPException(status_code=400, detail="项目名称不能为空")
    if "archived" in fields and fields["archived"] is None:
        raise HTTPException(status_code=400, detail="archived 必须是布尔值")
    guard = get_chat_execution_guard()
    project_lease = None
    if "archived" in fields:
        project_lease = guard.try_acquire_project_exclusive(project_id)
        if project_lease is None:
            raise HTTPException(status_code=409, detail="项目正在使用或变更，暂时不能归档")
    try:
        _require_project(user_id, project_id)
        project = get_chat_session_store().update_project(
            user_id, project_id, **fields
        )
        if project is None:
            raise HTTPException(status_code=404, detail="项目不存在")
        return project
    finally:
        if project_lease is not None:
            guard.release_project(project_lease)


@router.delete("/{project_id}")
async def delete_project(project_id: str, user_id: str = Depends(get_current_user_id)):
    _require_project(user_id, project_id)
    store = get_chat_session_store()
    guard = get_chat_execution_guard()
    project_lease = guard.try_acquire_project_exclusive(project_id)
    if project_lease is None:
        raise HTTPException(status_code=409, detail="项目正在使用或变更，暂时不能删除")
    session_ids: list[str] = []
    sessions_reserved = False
    try:
        _require_project(user_id, project_id)
        # 独占冻结后再取快照；新 chat、创建和迁入都已被阻止。session 锁
        # 继续覆盖并发迁出/删除，确保解绑与缓存驱逐使用同一组会话。
        affected_sessions = store.list_sessions(user_id, project_id=project_id)
        session_ids = [session["id"] for session in affected_sessions]
        if not guard.try_acquire_many(session_ids):
            raise HTTPException(
                status_code=409, detail="项目中有会话正在变更，暂时不能删除"
            )
        sessions_reserved = True
        deleted = store.delete_project(user_id, project_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="项目不存在")
        cleanup_pending = False
        try:
            get_project_workspace_manager().remove_project(project_id)
            store.complete_project_storage_cleanup(project_id)
        except Exception:
            cleanup_pending = True
            logger.exception(
                "删除项目共享资料目录失败，已保留重试任务 project=%s",
                project_id,
            )
        try:
            from app.services.open_harness_service import get_open_harness_service

            open_harness = get_open_harness_service()
            if open_harness is not None:
                for session in affected_sessions:
                    open_harness.reset_session(session["id"])
        except Exception:
            logger.exception("删除项目后驱逐 OpenHarness 会话失败 project=%s", project_id)
        return {
            "deleted": True,
            "sessions_preserved": True,
            "cleanup_pending": cleanup_pending,
        }
    finally:
        if sessions_reserved:
            guard.release_many(session_ids)
        guard.release_project(project_lease)


@router.get("/{project_id}/files")
async def list_project_files(project_id: str, user_id: str = Depends(get_current_user_id)):
    _require_project(user_id, project_id)
    return get_chat_session_store().list_project_files(user_id, project_id)


@router.post(
    "/{project_id}/files",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["file"],
                        "properties": {
                            "file": {"type": "string", "format": "binary"}
                        },
                    }
                }
            },
        }
    },
)
async def upload_project_file(
    project_id: str,
    request: Request,
    user_id: str = Depends(get_current_user_id),
):
    _require_project(user_id, project_id, active=True)
    guard = get_chat_execution_guard()
    if not guard.try_acquire_user_upload(user_id):
        raise HTTPException(status_code=429, detail="已有项目资料正在上传或导入，请稍后重试")
    project_lease = None
    form: Optional[FormData] = None
    try:
        project_lease = guard.try_acquire_project_shared(project_id)
        if project_lease is None:
            raise HTTPException(status_code=409, detail="项目正在变更，请稍后重试")
        _require_project(user_id, project_id, active=True)
        store = get_chat_session_store()
        capacity = store.get_project_file_capacity(user_id, project_id)
        if capacity is None:
            raise HTTPException(status_code=409, detail="项目已变化，请重试")
        max_size = _max_file_size_for_capacity(capacity)
        form, file = await _parse_single_upload(request, max_file_size=max_size)
        display_name = _safe_display_name(file.filename or "file")
        ext = _validate_extension(display_name)
        file_id = uuid.uuid4().hex
        storage_name = f"{file_id}{ext}"
        manager = get_project_workspace_manager()
        destination = manager.file_path(project_id, storage_name, create_parent=True)
        try:
            size, sha256 = await _stream_upload(
                file, destination, max_size=max_size
            )
            media_type = MEDIA_TYPES_BY_EXTENSION[ext]
            record = store.add_project_file(
                user_id,
                project_id,
                file_id=file_id,
                display_name=display_name,
                storage_name=storage_name,
                media_type=media_type,
                size_bytes=size,
                sha256=sha256,
                source_session_id=None,
            )
            return record
        except ProjectQuotaExceededError as exc:
            _discard_uncommitted_file(user_id, project_id, storage_name, destination)
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except ValueError as exc:
            _discard_uncommitted_file(user_id, project_id, storage_name, destination)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception:
            _discard_uncommitted_file(user_id, project_id, storage_name, destination)
            raise
    finally:
        try:
            if form is not None:
                await form.close()
        finally:
            if project_lease is not None:
                guard.release_project(project_lease)
            guard.release_user_upload(user_id)


@router.post("/{project_id}/files/import")
async def import_project_file(
    project_id: str,
    body: ImportProjectFileRequest,
    user_id: str = Depends(get_current_user_id),
):
    _require_project(user_id, project_id, active=True)
    guard = get_chat_execution_guard()
    if not guard.try_acquire_user_upload(user_id):
        raise HTTPException(status_code=429, detail="已有项目资料正在上传或导入，请稍后重试")
    project_lease = None
    source_session_reserved = False
    try:
        project_lease = guard.try_acquire_project_shared(project_id)
        if project_lease is None:
            raise HTTPException(status_code=409, detail="项目正在变更，请稍后重试")
        _require_project(user_id, project_id, active=True)
        try:
            validate_session_id(body.session_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store = get_chat_session_store()
        capacity = store.get_project_file_capacity(user_id, project_id)
        if capacity is None:
            raise HTTPException(status_code=409, detail="项目已变化，请重试")
        max_size = _max_file_size_for_capacity(capacity)
        if store.get_session(user_id, body.session_id) is None:
            raise HTTPException(status_code=404, detail="来源会话不存在")
        if not guard.try_acquire(body.session_id):
            raise HTTPException(status_code=409, detail="来源会话正在执行或变更，请稍后重试")
        source_session_reserved = True
        source_session = store.get_session(user_id, body.session_id)
        if source_session is None:
            raise HTTPException(status_code=404, detail="来源会话不存在")
        if source_session.get("project_id") != project_id:
            raise HTTPException(
                status_code=409,
                detail="来源会话当前不属于目标项目，不能将其产物保存为该项目资料",
            )
        source = _resolve_generated_output(body.session_id, body.path)
        if not source.exists() or not source.is_file():
            raise HTTPException(status_code=404, detail="来源文件不存在")
        display_name = _safe_display_name(body.display_name or source.name)
        source_ext = _validate_extension(source.name)
        ext = _validate_extension(display_name)
        if ext != source_ext:
            raise HTTPException(
                status_code=400,
                detail="资料显示名称必须保留生成产物的文件扩展名",
            )
        file_id = uuid.uuid4().hex
        storage_name = f"{file_id}{ext}"
        destination = get_project_workspace_manager().file_path(
            project_id, storage_name, create_parent=True
        )
        try:
            size, sha256 = _copy_file(source, destination, max_size=max_size)
            record = store.add_project_file(
                user_id,
                project_id,
                file_id=file_id,
                display_name=display_name,
                storage_name=storage_name,
                media_type=MEDIA_TYPES_BY_EXTENSION[ext],
                size_bytes=size,
                sha256=sha256,
                source_session_id=body.session_id,
            )
            return record
        except ProjectQuotaExceededError as exc:
            _discard_uncommitted_file(user_id, project_id, storage_name, destination)
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except ValueError as exc:
            _discard_uncommitted_file(user_id, project_id, storage_name, destination)
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception:
            _discard_uncommitted_file(user_id, project_id, storage_name, destination)
            raise
    finally:
        if source_session_reserved:
            guard.release(body.session_id)
        if project_lease is not None:
            guard.release_project(project_lease)
        guard.release_user_upload(user_id)


@router.get("/{project_id}/files/{file_id}")
async def get_project_file(
    project_id: str,
    file_id: str,
    download: bool = Query(False),
    user_id: str = Depends(get_current_user_id),
):
    _require_project(user_id, project_id)
    _validate_file_id_or_400(file_id)
    guard = get_chat_execution_guard()
    project_lease = guard.try_acquire_project_shared(project_id)
    if project_lease is None:
        raise HTTPException(status_code=409, detail="项目正在变更，请稍后重试")
    response_owns_lease = False
    try:
        _require_project(user_id, project_id)
        record = get_chat_session_store().get_project_file(
            user_id, project_id, file_id, include_storage=True
        )
        if record is None:
            raise HTTPException(status_code=404, detail="项目资料不存在")
        try:
            path = get_project_workspace_manager().file_path(
                project_id, record["storage_name"]
            )
        except ValueError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="项目资料文件不存在")
        response = _LeaseFileResponse(
            path,
            media_type=record.get("media_type") or "application/octet-stream",
            filename=record["display_name"],
            content_disposition_type=(
                "attachment"
                if download
                or Path(record["display_name"]).suffix.lower()
                in FORCE_ATTACHMENT_EXTENSIONS
                else "inline"
            ),
            headers={"X-Content-Type-Options": "nosniff"},
            release_lease=lambda: guard.release_project(project_lease),
        )
        response_owns_lease = True
        return response
    finally:
        if not response_owns_lease:
            guard.release_project(project_lease)


@router.delete("/{project_id}/files/{file_id}")
async def delete_project_file(
    project_id: str,
    file_id: str,
    user_id: str = Depends(get_current_user_id),
):
    _require_project(user_id, project_id)
    _validate_file_id_or_400(file_id)
    store = get_chat_session_store()
    guard = get_chat_execution_guard()
    project_lease = guard.try_acquire_project_exclusive(project_id)
    if project_lease is None:
        raise HTTPException(status_code=409, detail="项目正在使用或变更，暂时不能删除资料")
    try:
        _require_project(user_id, project_id)
        record = store.get_project_file(
            user_id, project_id, file_id, include_storage=True
        )
        if record is None:
            raise HTTPException(status_code=404, detail="项目资料不存在")
        deleted = store.delete_project_file(user_id, project_id, file_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="项目资料不存在")
        cleanup_pending = False
        try:
            get_project_workspace_manager().remove_file(
                project_id, record["storage_name"]
            )
            store.complete_storage_cleanup(
                resource_type="file",
                project_id=project_id,
                storage_name=record["storage_name"],
            )
        except Exception:
            cleanup_pending = True
            logger.exception(
                "删除项目资料文件失败，已保留重试任务 project=%s file=%s",
                project_id,
                file_id,
            )
        return {"deleted": True, "cleanup_pending": cleanup_pending}
    finally:
        guard.release_project(project_lease)
