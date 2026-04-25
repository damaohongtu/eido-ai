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


class SessionWorkspaceManager:
    """会话工作区管理器（无状态，所有操作幂等）。"""

    def __init__(self, root: Optional[Path] = None):
        self._root = (root or Path(settings.WORKSPACE_ROOT) / ".eido" / "workspaces").resolve()
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
