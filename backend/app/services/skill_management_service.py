"""
技能管理服务 — CRUD 与文件操作

从 claude_skill_service.py 中提取的技能管理相关方法，
包括创建、更新、删除技能，以及技能目录下的文件管理操作。
"""
import logging
import shutil
from pathlib import Path
from typing import List, Optional

from app.services.claude_skill_service import SkillMeta, USER_UPLOAD_MARKER

logger = logging.getLogger(__name__)


class SkillManagementService:
    """技能管理服务：CRUD + 文件操作"""

    def __init__(self, skills_dir: Path, workspace_root: Path, execution_service):
        self.skills_dir = skills_dir
        self.workspace_root = workspace_root
        self._execution_service = execution_service

    # ------------------------------------------------------------------ #
    #  路径安全                                                             #
    # ------------------------------------------------------------------ #

    def _get_skill_dir(self, skill_id: str) -> Path:
        """验证 skill_id 安全并返回解析后的技能目录路径"""
        if not skill_id or any(sep in skill_id for sep in ("/", "\\", "..")):
            raise ValueError("无效的技能 ID")

        skill_dir = (self.skills_dir / skill_id).resolve()
        base = self.skills_dir.resolve()
        try:
            skill_dir.relative_to(base)
        except ValueError:
            raise ValueError("无效的技能路径") from None

        if not (skill_dir / "SKILL.md").exists():
            raise FileNotFoundError(f"技能不存在: {skill_id}")
        return skill_dir

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

    def create_skill(self, name: str, description: str, content: str, icon: Optional[str] = None) -> SkillMeta:
        """创建新技能目录并写入 SKILL.md"""
        skill_id = self._slug(name)
        target_dir = self.skills_dir / skill_id
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
            (target_dir / USER_UPLOAD_MARKER).write_text("", encoding="utf-8")
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise

        return self._execution_service.get_skill(skill_id)

    def update_skill(self, skill_id: str, name: Optional[str] = None, description: Optional[str] = None,
                     content: Optional[str] = None, icon: Optional[str] = None) -> SkillMeta:
        """更新技能元数据或正文；系统技能不可修改"""
        from app.services.claude_skill_service import _parse_frontmatter

        skill_dir = self._get_skill_dir(skill_id)
        if not (skill_dir / USER_UPLOAD_MARKER).exists():
            raise PermissionError("系统技能不可修改")

        existing = self._execution_service.get_skill(skill_id)
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

        return self._execution_service.get_skill(skill_id)

    def mark_user_upload(self, skill_id: str) -> None:
        """将技能目录标记为用户上传安装，允许后续删除。"""
        skill_dir = self.skills_dir / skill_id
        if not (skill_dir / "SKILL.md").exists():
            raise FileNotFoundError(f"技能不存在: {skill_id}")
        (skill_dir / USER_UPLOAD_MARKER).write_text("", encoding="utf-8")

    def delete_user_upload(self, skill_id: str) -> None:
        """删除用户上传的技能目录；系统技能（无标记）不可删。"""
        if not skill_id or any(sep in skill_id for sep in ("/", "\\", "..")):
            raise ValueError("无效的技能 ID")

        skill_dir = (self.skills_dir / skill_id).resolve()
        base = self.skills_dir.resolve()
        try:
            skill_dir.relative_to(base)
        except ValueError:
            raise ValueError("无效的技能路径") from None

        if not (skill_dir / "SKILL.md").exists():
            raise FileNotFoundError(f"技能不存在: {skill_id}")
        if not (skill_dir / USER_UPLOAD_MARKER).exists():
            raise PermissionError("仅支持删除通过上传安装的技能")

        shutil.rmtree(skill_dir)
        logger.info("已删除用户上传技能: %s", skill_id)

    # ------------------------------------------------------------------ #
    #  文件管理                                                             #
    # ------------------------------------------------------------------ #

    def list_files(self, skill_id: str) -> List[dict]:
        """递归列出技能目录下所有文件（树形结构）"""
        skill_dir = self._get_skill_dir(skill_id)

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

    def read_file(self, skill_id: str, path: str) -> dict:
        """读取技能目录下指定文件内容"""
        skill_dir = self._get_skill_dir(skill_id)
        file_path = self._validate_file_path(skill_dir, path)
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError(f"文件不存在: {path}")
        content = file_path.read_text(encoding="utf-8")
        return {"path": path, "content": content, "size": file_path.stat().st_size}

    def write_file(self, skill_id: str, path: str, content: str) -> None:
        """向技能目录写入文件"""
        skill_dir = self._get_skill_dir(skill_id)
        if not (skill_dir / USER_UPLOAD_MARKER).exists():
            raise PermissionError("系统技能不可修改")
        file_path = self._validate_file_path(skill_dir, path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    def delete_file(self, skill_id: str, path: str) -> None:
        """删除技能目录下指定文件或目录（目录递归删除）；禁止删除 SKILL.md"""
        skill_dir = self._get_skill_dir(skill_id)
        if not (skill_dir / USER_UPLOAD_MARKER).exists():
            raise PermissionError("系统技能不可修改")
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

    def mkdir(self, skill_id: str, path: str) -> None:
        """在技能目录下创建子目录"""
        skill_dir = self._get_skill_dir(skill_id)
        if not (skill_dir / USER_UPLOAD_MARKER).exists():
            raise PermissionError("系统技能不可修改")
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
