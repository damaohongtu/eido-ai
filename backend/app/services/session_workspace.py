"""
按 session_id 隔离的会话工作区。

每个会话的所有上传文件、agent 生成产物都被约束在 `.eido/workspaces/<session_id>/` 内，
agent 执行时 cwd 切到该目录，杜绝跨会话文件污染。
"""
from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

UPLOADS_SUBDIR = "uploads"
OUTPUTS_SUBDIR = "outputs"


def validate_session_id(session_id: str) -> str:
    """校验 session_id 字符白名单，防路径遍历。返回原 id；非法时抛 ValueError。"""
    if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
        raise ValueError(f"非法 session_id: {session_id!r}（仅允许字母数字下划线连字符，长度 1-64）")
    return session_id


class _FileNode:
    __slots__ = ("name", "path", "type", "children")

    def __init__(self, name: str, path: str, type_: str, children: list | None = None):
        self.name = name
        self.path = path
        self.type = type_
        self.children = children or []

    def to_dict(self):
        d = {"name": self.name, "path": self.path, "type": self.type}
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d


class SessionWorkspaceManager:
    """会话工作区管理器（无状态，所有操作幂等）。"""

    _SKIP_NAMES = {".DS_Store", "Thumbs.db"}

    def __init__(self, root: Optional[Path] = None):
        self._root = (root or settings.workspaces_root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def session_root(self, session_id: str, *, create: bool = True) -> Path:
        """返回该会话的工作区根目录，create=True 时确保子目录存在。"""
        validate_session_id(session_id)
        sess_dir = (self._root / session_id).resolve()
        try:
            sess_dir.relative_to(self._root)
        except ValueError as e:
            raise ValueError(f"session 目录越界: {sess_dir}") from e
        if create:
            (sess_dir / UPLOADS_SUBDIR).mkdir(parents=True, exist_ok=True)
            (sess_dir / OUTPUTS_SUBDIR).mkdir(parents=True, exist_ok=True)
        return sess_dir

    def uploads_dir(self, session_id: str) -> Path:
        return self.session_root(session_id) / UPLOADS_SUBDIR

    def outputs_dir(self, session_id: str) -> Path:
        return self.session_root(session_id) / OUTPUTS_SUBDIR

    def safe_resolve(self, session_id: str, rel_or_abs_path: str) -> Path:
        """将外部传入的路径解析为绝对路径，并校验其落在该 session 工作区内。"""
        sess_dir = self.session_root(session_id, create=False)
        p = Path(rel_or_abs_path)
        resolved = (p if p.is_absolute() else sess_dir / p).resolve()
        try:
            resolved.relative_to(sess_dir)
        except ValueError as e:
            raise ValueError(f"路径不在 session {session_id} 工作区内: {rel_or_abs_path}") from e
        return resolved

    def _scan_dir(self, dir_path: Path, root_path: Path) -> list[_FileNode]:
        nodes: list[_FileNode] = []
        try:
            entries = sorted(dir_path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except OSError:
            return nodes
        for entry in entries:
            if entry.name in self._SKIP_NAMES:
                continue
            rel = str(entry.relative_to(root_path))
            if entry.is_dir():
                node = _FileNode(entry.name, rel, "directory")
                node.children = self._scan_dir(entry, root_path)
                if node.children:
                    nodes.append(node)
            else:
                nodes.append(_FileNode(entry.name, rel, "file"))
        return nodes

    def list_directory(self, session_id: str) -> list[_FileNode]:
        validate_session_id(session_id)
        root = self.session_root(session_id, create=False)
        if not root.exists():
            return []
        return self._scan_dir(root, root)

    def delete_file(self, session_id: str, path: str) -> bool:
        validate_session_id(session_id)
        resolved = self.safe_resolve(session_id, path)
        if not resolved.exists():
            return False
        if resolved.is_dir():
            shutil.rmtree(resolved, ignore_errors=True)
        else:
            resolved.unlink(missing_ok=True)
        logger.info(f"已删除 session 工作区文件: {resolved}")
        return True

    def remove(self, session_id: str) -> bool:
        """删除整个会话工作区目录。不存在时返回 False。"""
        validate_session_id(session_id)
        sess_dir = (self._root / session_id).resolve()
        try:
            sess_dir.relative_to(self._root)
        except ValueError:
            logger.warning(f"拒绝删除越界目录: {sess_dir}")
            return False
        if not sess_dir.exists():
            return False
        shutil.rmtree(sess_dir, ignore_errors=True)
        logger.info(f"已删除 session 工作区: {sess_dir}")
        return True


_instance: Optional[SessionWorkspaceManager] = None


def get_session_workspace_manager() -> SessionWorkspaceManager:
    """全局单例。第一次调用时自动初始化。"""
    global _instance
    if _instance is None:
        _instance = SessionWorkspaceManager()
        logger.info(f"SessionWorkspaceManager 初始化: {_instance.root}")
    return _instance
