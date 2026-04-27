"""
技能管理服务 — CRUD 与文件操作（按用户身份隔离）

目录布局（v2）：
  $SKILLS_DIR/system/<id>/        # admin 上传 / 内置，所有用户只读可见
  $SKILLS_DIR/users/<safe>/<id>/  # 普通用户私有，仅本人可见可改

权限判定：
- admin 白名单（EIDO_ADMIN_USERS）：可在 system/ 创建/修改/删除技能
- 普通用户：只能在 users/<self>/ 下创建/修改/删除，且不可触碰 system/
"""
import logging
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from app.core.config import settings
from app.gateway.sandbox_manager import _safe_user_id
from app.services.claude_skill_service import (
    SYSTEM_SUBDIR,
    USER_UPLOAD_MARKER,
    USERS_SUBDIR,
    SkillMeta,
)

logger = logging.getLogger(__name__)


class SkillManagementService:
    """技能管理服务：CRUD + 文件操作（按用户隔离）"""

    def __init__(self, skills_dir: Path, workspace_root: Path, execution_service):
        self.skills_dir = skills_dir
        self.workspace_root = workspace_root
        self._execution_service = execution_service

    # ------------------------------------------------------------------ #
    #  目录与权限                                                           #
    # ------------------------------------------------------------------ #

    @property
    def _system_root(self) -> Path:
        return self.skills_dir / SYSTEM_SUBDIR

    def _user_root(self, user_id: str) -> Path:
        return self.skills_dir / USERS_SUBDIR / _safe_user_id(user_id)

    def _resolve_owner_dir(self, user_id: str) -> Path:
        """根据 user_id 决定新建技能落到哪个根目录。"""
        if settings.is_admin(user_id):
            target = self._system_root
        else:
            if not user_id:
                raise PermissionError("缺少用户身份，无法创建技能")
            target = self._user_root(user_id)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def _locate_skill(
        self, skill_id: str, user_id: Optional[str]
    ) -> Tuple[Path, str]:
        """定位技能目录。优先用户私有 → system，返回 (skill_dir, owner_type)。"""
        if not skill_id or any(sep in skill_id for sep in ("/", "\\", "..")):
            raise ValueError("无效的技能 ID")

        if user_id:
            user_dir = self._user_root(user_id) / skill_id
            if (user_dir / "SKILL.md").exists():
                return user_dir.resolve(), "user"

        sys_dir = self._system_root / skill_id
        if (sys_dir / "SKILL.md").exists():
            return sys_dir.resolve(), "system"

        raise FileNotFoundError(f"技能不存在: {skill_id}")

    def _check_write_perm(self, owner_type: str, user_id: str) -> None:
        """根据 owner_type 校验 user_id 是否有写权限。"""
        if owner_type == "system":
            if not settings.is_admin(user_id):
                raise PermissionError("仅管理员可修改系统技能")
        elif owner_type == "user":
            # owner_type=user 时调用方一定是从 _user_root(user_id) 命中的，
            # 即此处 user_id 就是 owner，无需额外校验。
            if not user_id:
                raise PermissionError("缺少用户身份")
        else:
            raise PermissionError(f"未知 owner_type: {owner_type}")

    def _validate_file_path(self, skill_dir: Path, path: str) -> Path:
        """验证文件路径不逃逸出技能目录，返回解析后的 Path"""
        if not path or ".." in path:
            raise ValueError("无效的文件路径")

        file_path = (skill_dir / path).resolve()
        try:
            file_path.relative_to(skill_dir.resolve())
        except ValueError:
            raise ValueError("文件路径超出技能目录范围") from None
        return file_path

    @staticmethod
    def _slug(name: str) -> str:
        """将名称转为目录名 slug"""
        import re
        s = re.sub(r"[^\w\s-]", "", name)
        s = re.sub(r"[-\s]+", "-", s).strip().lower()
        return s or "skill"

    # ------------------------------------------------------------------ #
    #  技能 CRUD                                                           #
    # ------------------------------------------------------------------ #

    def create_skill(
        self,
        user_id: str,
        name: str,
        description: str,
        content: str,
        icon: Optional[str] = None,
    ) -> SkillMeta:
        """在调用者所属区域（admin → system，其他 → 私有）创建新技能。"""
        skill_id = self._slug(name)
        owner_root = self._resolve_owner_dir(user_id)
        target_dir = owner_root / skill_id
        if target_dir.exists():
            raise ValueError(f"技能已存在: {skill_id}")

        target_dir.mkdir(parents=True)
        try:
            import yaml
            frontmatter = {"name": name, "description": description}
            if icon:
                frontmatter["icon"] = icon
            fm_text = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False)
            skill_md = f"---\n{fm_text}---\n\n{content}"
            (target_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise

        return self._execution_service.get_skill(skill_id, user_id=user_id)

    def update_skill(
        self,
        user_id: str,
        skill_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        content: Optional[str] = None,
        icon: Optional[str] = None,
    ) -> SkillMeta:
        """更新技能元数据或正文。系统技能仅 admin 可改，私有技能仅 owner 可改。"""
        from app.services.claude_skill_service import _parse_frontmatter

        skill_dir, owner_type = self._locate_skill(skill_id, user_id)
        self._check_write_perm(owner_type, user_id)

        existing = self._execution_service.get_skill(skill_id, user_id=user_id)
        meta, body = _parse_frontmatter(existing.content)

        if "name" not in meta:
            meta["name"] = existing.name
        if "description" not in meta:
            meta["description"] = existing.description

        if name is not None:
            meta["name"] = name
        if description is not None:
            meta["description"] = description
        if icon is not None:
            meta["icon"] = icon
        if content is not None:
            body = content

        import yaml
        fm_text = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
        new_text = f"---\n{fm_text}---\n\n{body}"
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(new_text, encoding="utf-8")

        return self._execution_service.get_skill(skill_id, user_id=user_id)

    def delete_skill(self, user_id: str, skill_id: str) -> None:
        """按权限删除技能目录。系统技能仅 admin 可删；私有技能仅 owner 可删。"""
        skill_dir, owner_type = self._locate_skill(skill_id, user_id)
        self._check_write_perm(owner_type, user_id)
        shutil.rmtree(skill_dir)
        logger.info(
            "已删除技能 user=%s owner_type=%s id=%s", user_id, owner_type, skill_id
        )

    # 兼容旧别名：endpoints 中曾用 delete_user_upload
    delete_user_upload = delete_skill

    def mark_user_upload(self, skill_id: str, user_id: Optional[str] = None) -> None:
        """兼容历史：保留以备旧 zip 上传调用。新版不再依赖此标记。"""
        try:
            skill_dir, _ = self._locate_skill(skill_id, user_id)
        except FileNotFoundError:
            return
        try:
            (skill_dir / USER_UPLOAD_MARKER).write_text("", encoding="utf-8")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  文件管理                                                             #
    # ------------------------------------------------------------------ #

    def list_files(self, user_id: Optional[str], skill_id: str) -> List[dict]:
        """递归列出技能目录下所有文件（树形结构）。读权限：system 任意人可读。"""
        skill_dir, _ = self._locate_skill(skill_id, user_id)

        def walk(dir_path: Path, rel_prefix: str = "") -> List[dict]:
            items: List[dict] = []
            for entry in sorted(dir_path.iterdir()):
                rel = f"{rel_prefix}/{entry.name}" if rel_prefix else entry.name
                if entry.name == USER_UPLOAD_MARKER or entry.name == "__pycache__" or entry.suffix == ".pyc":
                    continue
                if entry.is_dir():
                    children = walk(entry, rel)
                    items.append({"name": entry.name, "path": rel, "type": "dir", "children": children})
                else:
                    items.append({"name": entry.name, "path": rel, "type": "file", "size": entry.stat().st_size})
            return items

        return walk(skill_dir)

    def read_file(self, user_id: Optional[str], skill_id: str, path: str) -> dict:
        """读取技能目录下指定文件内容。"""
        skill_dir, _ = self._locate_skill(skill_id, user_id)
        file_path = self._validate_file_path(skill_dir, path)
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"文件不存在: {path}")
        content = file_path.read_text(encoding="utf-8")
        return {"path": path, "content": content, "size": file_path.stat().st_size}

    def write_file(self, user_id: str, skill_id: str, path: str, content: str) -> None:
        """向技能目录写入文件。"""
        skill_dir, owner_type = self._locate_skill(skill_id, user_id)
        self._check_write_perm(owner_type, user_id)
        file_path = self._validate_file_path(skill_dir, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    def delete_file(self, user_id: str, skill_id: str, path: str) -> None:
        """删除技能目录下指定文件或目录（目录递归删除）；禁止删除 SKILL.md"""
        skill_dir, owner_type = self._locate_skill(skill_id, user_id)
        self._check_write_perm(owner_type, user_id)
        if not path or path in (".", "/"):
            raise PermissionError("禁止删除技能根目录")
        file_path = self._validate_file_path(skill_dir, path)
        resolved = file_path.resolve()
        if resolved.name == "SKILL.md":
            raise PermissionError("禁止删除 SKILL.md")
        if resolved == skill_dir.resolve():
            raise PermissionError("禁止删除技能根目录")
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {path}")
        if file_path.is_file():
            file_path.unlink()
        elif file_path.is_dir():
            shutil.rmtree(file_path)
        else:
            raise ValueError("未知文件类型")

    def mkdir(self, user_id: str, skill_id: str, path: str) -> None:
        """在技能目录下创建子目录"""
        skill_dir, owner_type = self._locate_skill(skill_id, user_id)
        self._check_write_perm(owner_type, user_id)
        dir_path = self._validate_file_path(skill_dir, path)
        dir_path.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------ #
#  全局单例                                                             #
# ------------------------------------------------------------------ #

_instance: Optional[SkillManagementService] = None


def get_skill_management_service() -> Optional[SkillManagementService]:
    return _instance


def init_skill_management_service(skills_dir: Path, workspace_root: Path, execution_service) -> SkillManagementService:
    global _instance
    _instance = SkillManagementService(skills_dir, workspace_root, execution_service)
    return _instance
