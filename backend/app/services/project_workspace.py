"""Project shared-file storage.

Project files are intentionally separate from session workspaces.  A project is
shared context, while a session remains the writable execution/cwd boundary.
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.core.config import settings
from app.services.supported_files import SUPPORTED_FILE_EXTENSIONS

if TYPE_CHECKING:
    from app.services.chat_session_store import ChatSessionStore

logger = logging.getLogger(__name__)

PROJECT_FILE_EXTENSIONS = SUPPORTED_FILE_EXTENSIONS
_PROJECT_FILE_EXTENSION_PATTERN = "(?:" + "|".join(
    re.escape(extension) for extension in sorted(PROJECT_FILE_EXTENSIONS)
) + ")"
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_GENERATED_PROJECT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_GENERATED_STORAGE_RE = re.compile(
    rf"^[0-9a-f]{{32}}{_PROJECT_FILE_EXTENSION_PATTERN}$"
)
_TEMP_STORAGE_RE = re.compile(
    rf"^\.[0-9a-f]{{32}}{_PROJECT_FILE_EXTENSION_PATTERN}"
    rf"\.[0-9a-f]{{32}}\.(?:upload|import)$"
)
FILES_SUBDIR = "files"


def validate_project_id(project_id: str) -> str:
    if not isinstance(project_id, str) or not _SAFE_ID_RE.fullmatch(project_id):
        raise ValueError("非法 project_id（仅允许字母、数字、下划线和连字符，长度 1-64）")
    return project_id


def validate_project_file_id(file_id: str) -> str:
    if not isinstance(file_id, str) or not _SAFE_ID_RE.fullmatch(file_id):
        raise ValueError("非法 file_id（仅允许字母、数字、下划线和连字符，长度 1-64）")
    return file_id


class ProjectWorkspaceManager:
    """Resolve and remove project files without exposing arbitrary paths."""

    def __init__(self, root: Optional[Path] = None):
        self._root = (root or settings.projects_root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def project_root(self, project_id: str, *, create: bool = True) -> Path:
        validate_project_id(project_id)
        path = self._root / project_id
        if path.is_symlink():
            raise ValueError("项目目录不能是符号链接")
        if create:
            path.mkdir(parents=True, exist_ok=True)
        if path.exists() and not path.is_dir():
            raise ValueError("项目路径不是目录")
        resolved = path.resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise ValueError("项目目录越界") from exc
        if create:
            files_dir = path / FILES_SUBDIR
            if files_dir.is_symlink():
                raise ValueError("项目文件目录不能是符号链接")
            files_dir.mkdir(parents=True, exist_ok=True)
        return path

    def files_dir(self, project_id: str, *, create: bool = True) -> Path:
        path = self.project_root(project_id, create=create) / FILES_SUBDIR
        if path.is_symlink():
            raise ValueError("项目文件目录不能是符号链接")
        if path.exists() and not path.is_dir():
            raise ValueError("项目文件路径不是目录")
        return path

    def file_path(self, project_id: str, storage_name: str, *, create_parent: bool = False) -> Path:
        if not storage_name or Path(storage_name).name != storage_name:
            raise ValueError("非法项目文件存储名")
        files_dir = self.files_dir(project_id, create=create_parent)
        path = files_dir / storage_name
        if path.is_symlink():
            raise ValueError("项目文件不能是符号链接")
        resolved = path.resolve()
        try:
            resolved.relative_to(files_dir.resolve())
        except ValueError as exc:
            raise ValueError("项目文件路径越界") from exc
        return path

    def remove_file(self, project_id: str, storage_name: str) -> bool:
        validate_project_id(project_id)
        if not storage_name or Path(storage_name).name != storage_name:
            raise ValueError("非法项目文件存储名")
        project_path = self._root / project_id
        if project_path.is_symlink():
            raise ValueError("项目目录不能是符号链接")
        files_dir = project_path / FILES_SUBDIR
        if files_dir.is_symlink():
            raise ValueError("项目文件目录不能是符号链接")
        path = files_dir / storage_name
        if path.is_symlink():
            path.unlink()
            return True
        if not path.exists():
            return False
        if not path.is_file():
            raise ValueError("项目文件路径不是普通文件")
        path.unlink()
        return True

    def remove_project(self, project_id: str) -> bool:
        validate_project_id(project_id)
        path = self._root / project_id
        if path.is_symlink():
            path.unlink()
            logger.warning("删除了项目目录符号链接而未跟随目标: %s", path)
            return True
        if not path.exists():
            return False
        if not path.is_dir():
            raise ValueError("项目路径不是目录")
        shutil.rmtree(path)
        logger.info("已删除项目共享资料目录: %s", path)
        return True


_instance: Optional[ProjectWorkspaceManager] = None


def get_project_workspace_manager() -> ProjectWorkspaceManager:
    global _instance
    if _instance is None:
        _instance = ProjectWorkspaceManager()
        logger.info("ProjectWorkspaceManager 初始化: %s", _instance.root)
    return _instance


def _enqueue_project_orphans(
    store: "ChatSessionStore",
    project_path: Path,
    project_owners: dict[str, str],
    file_keys: set[tuple[str, str]],
) -> int:
    """Reconcile one Project directory; callers isolate per-directory I/O errors."""
    project_id = project_path.name
    if project_id.startswith(".") or not _SAFE_ID_RE.fullmatch(project_id):
        return 0
    if project_id not in project_owners:
        if _GENERATED_PROJECT_ID_RE.fullmatch(project_id):
            store.enqueue_storage_cleanup(
                resource_type="project", project_id=project_id
            )
        return 0
    if project_path.is_symlink() or not project_path.is_dir():
        logger.error("项目目录损坏或为符号链接: %s", project_path)
        return 1
    files_dir = project_path / FILES_SUBDIR
    if not files_dir.exists():
        return 0
    if files_dir.is_symlink() or not files_dir.is_dir():
        logger.error("项目文件目录损坏或为符号链接: %s", files_dir)
        return 1
    for path in files_dir.iterdir():
        storage_name = path.name
        if (project_id, storage_name) in file_keys:
            continue
        if _GENERATED_STORAGE_RE.fullmatch(
            storage_name
        ) or _TEMP_STORAGE_RE.fullmatch(storage_name):
            size_bytes = 0
            if not path.is_symlink() and path.is_file():
                size_bytes = path.stat().st_size
            store.enqueue_storage_cleanup(
                resource_type="file",
                project_id=project_id,
                storage_name=storage_name,
                user_id=project_owners[project_id],
                file_count=1,
                size_bytes=size_bytes,
            )
    return 0


def retry_pending_storage_cleanup(
    store: "ChatSessionStore",
    *,
    limit: int = 1000,
    reconcile_orphans: bool = True,
) -> dict[str, int]:
    """Retry filesystem deletions recorded atomically with metadata deletion.

    A failed unlink/rmtree must remain discoverable after the public metadata is
    gone.  Jobs live in SQLite and are retried at startup; the existence checks
    prevent a stale job from deleting a resource that has since been recreated.
    """
    manager = get_project_workspace_manager()
    project_owners, file_keys = store.project_storage_index()
    missing = 0
    completed = 0
    failed = 0

    # Recover the two add-file crash windows: a process can stop after writing
    # its generated temp/final name but before metadata commit/compensation.
    # Only server-generated names are eligible; unrelated files are untouched.
    project_paths = manager.root.iterdir() if reconcile_orphans else ()
    for project_path in project_paths:
        try:
            missing += _enqueue_project_orphans(
                store, project_path, project_owners, file_keys
            )
        except OSError:
            failed += 1
            logger.exception("跳过无法读取的项目目录: %s", project_path)

    if reconcile_orphans:
        for project_id, storage_name in file_keys:
            path = manager.root / project_id / FILES_SUBDIR / storage_name
            try:
                unsafe_or_missing = path.is_symlink() or not path.is_file()
            except OSError:
                failed += 1
                logger.exception("无法检查项目文件: %s", path)
                continue
            if unsafe_or_missing:
                missing += 1
                logger.error(
                    "项目文件元数据存在但磁盘文件缺失或不安全: project=%s storage=%s",
                    project_id,
                    storage_name,
                )

    for job in store.list_storage_cleanup_jobs(limit=limit):
        resource_type = job["resource_type"]
        project_id = job["project_id"]
        storage_name = job.get("storage_name") or ""
        try:
            if resource_type == "project":
                if not store.project_resource_exists(project_id):
                    manager.remove_project(project_id)
                    store.complete_project_storage_cleanup(project_id)
                else:
                    # A stale whole-Project job must not erase valid per-file
                    # cleanup jobs belonging to a currently active Project.
                    store.complete_storage_cleanup(
                        resource_type="project", project_id=project_id
                    )
                completed += 1
                continue
            elif resource_type == "file":
                if not store.project_file_resource_exists(project_id, storage_name):
                    manager.remove_file(project_id, storage_name)
            else:
                raise ValueError(f"未知清理任务类型: {resource_type}")
            store.complete_storage_cleanup(
                resource_type=resource_type,
                project_id=project_id,
                storage_name=storage_name,
            )
            completed += 1
        except Exception as exc:
            failed += 1
            store.record_storage_cleanup_failure(job["id"], str(exc))
            logger.exception("项目存储清理失败 job=%s", job["id"])
    return {"completed": completed, "failed": failed, "missing": missing}
