"""
Claude Code skill discovery and native session view materialization.

技能定义维护在 .claude/skills/ 目录下的 SKILL.md 文件中，
通过 claude_agent_sdk 自动规划执行，无需数据库。
用户请求无需携带 skill_id，由 claude_agent_sdk 从用户输入中自动选择并执行技能。

目录布局：
  $SKILLS_DIR/
    system/<id>/SKILL.md          # admin 上传/内置，所有用户只读可见
    users/<safe_user_id>/<id>/    # 用户私有，仅本人可改

权限通过路径区分：在 system/ 下即系统技能；在 users/<uid>/ 下即该用户私有。
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from app.gateway.sandbox_manager import _safe_user_id

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_TOOLS = ["Bash", "Glob", "Read", "WebFetch"]

# 技能列表 API 会在页面装载期间被并发请求多次。缓存命中时不再遍历/解析
# SKILL.md；TTL 到期后先比较轻量 stat 指纹，内容未变则继续复用对象。
SKILL_CACHE_TTL_SEC = 5.0

_NATIVE_SKILLS_MANIFEST = ".eido-native-skills.json"

# 历史标记文件：保留以兼容旧目录扫描，不再作为权限判定依据
USER_UPLOAD_MARKER = ".eido-user-upload"

SYSTEM_SUBDIR = "system"
USERS_SUBDIR = "users"


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """解析 YAML frontmatter，返回 (metadata, body)。

    支持两种 allowed_tools 写法：
      - YAML 多行列表（需要 pyyaml）
      - 逗号分隔字符串（简单 fallback）
    """
    if not content.startswith("---"):
        return {}, content

    end = content.find("\n---", 3)
    if end == -1:
        return {}, content

    fm_text = content[3:end].strip()
    body = content[end + 4 :].lstrip("\n")

    try:
        import yaml  # type: ignore

        metadata = yaml.safe_load(fm_text) or {}
    except Exception:
        # 简单 fallback：仅支持 key: value 单行，不支持 YAML list
        metadata: dict = {}
        for line in fm_text.splitlines():
            if ": " in line and not line.startswith(" ") and not line.startswith("-"):
                k, _, v = line.partition(": ")
                metadata[k.strip()] = v.strip()

    return metadata, body


@dataclass
class SkillMeta:
    """技能元数据，从 SKILL.md frontmatter 解析"""

    id: str  # 目录名，即 slug，如 financial-report-analyst
    name: str
    description: str
    allowed_tools: List[str]
    content: str  # SKILL.md 完整原文
    skill_dir: Path
    created_at: str = ""
    updated_at: str = ""
    is_active: bool = True
    is_system: bool = True
    is_public: bool = True
    version: int = 1
    usage_count: int = 0
    user_id: Optional[str] = None
    icon: Optional[str] = None
    output_schema: Optional[dict] = None
    tools: list = field(default_factory=list)
    agents: list = field(default_factory=list)
    # 所属类型：system | user
    owner_type: str = "system"
    # 当 owner_type == user 时记录原始 user_id（即 CAS username）
    owner_user_id: Optional[str] = None


@dataclass
class _SkillCacheEntry:
    skills: tuple[SkillMeta, ...]
    fingerprint: tuple[tuple[str, str, int, int], ...]
    expires_at: float


class SkillCatalog:
    def __init__(self, skills_dir: Path, workspace_root: Path):
        self.skills_dir = skills_dir
        self.workspace_root = workspace_root
        self._skill_cache = {}
        self._native_skill_views = {}

    # ------------------------------------------------------------------ #
    #  技能发现                                                             #
    # ------------------------------------------------------------------ #

    @property
    def system_dir(self) -> Path:
        return self.skills_dir / SYSTEM_SUBDIR

    def user_private_dir(self, user_id: str) -> Path:
        """返回某 user_id 的私有技能根目录（不保证存在）。"""
        return self.skills_dir / USERS_SUBDIR / _safe_user_id(user_id)

    def _scan_dir(
        self,
        root: Path,
        *,
        owner_type: str,
        owner_user_id: Optional[str] = None,
    ) -> List[SkillMeta]:
        skills: List[SkillMeta] = []
        if not root.exists():
            return skills
        for skill_dir in sorted(root.iterdir()):
            if not skill_dir.is_dir():
                continue
            if not (skill_dir / "SKILL.md").exists():
                continue
            try:
                meta = self._load_skill(
                    skill_dir,
                    owner_type=owner_type,
                    owner_user_id=owner_user_id,
                )
                skills.append(meta)
            except Exception as e:
                logger.warning(f"加载技能失败 [{skill_dir.name}]: {e}")
        return skills

    def _catalog_fingerprint(
        self, *, user_id: Optional[str]
    ) -> tuple[tuple[str, str, int, int], ...]:
        """只读取目录项和 SKILL.md stat，避免为未变化目录重复解析正文。"""
        roots = [("system", self.system_dir)]
        if user_id:
            roots.append(("user", self.user_private_dir(user_id)))
        entries: list[tuple[str, str, int, int]] = []
        for owner_type, root in roots:
            if not root.exists():
                continue
            for skill_dir in sorted(root.iterdir()):
                skill_md = skill_dir / "SKILL.md"
                if not skill_dir.is_dir() or not skill_md.is_file():
                    continue
                try:
                    stat = skill_md.stat()
                except OSError:
                    continue
                entries.append(
                    (owner_type, str(skill_dir.resolve()), stat.st_mtime_ns, stat.st_size)
                )
        return tuple(entries)

    def invalidate_skill_cache(
        self, *, user_id: Optional[str] = None, system: bool = False
    ) -> None:
        """技能 CRUD 后主动失效；system 变化会影响所有用户视图。"""
        if system or user_id is None:
            self._skill_cache.clear()
            affected_user: Optional[str] = None
        else:
            self._skill_cache.pop(user_id, None)
            affected_user = user_id
        self._on_catalog_changed(affected_user)

    def scan_skills(self, *, user_id: Optional[str] = None) -> List[SkillMeta]:
        """扫描 system 区 +（若给定 user_id）该用户私有区。

        合并策略：同 id 在 user 私有与 system 中都存在时，user 区覆盖 system 区，
        仅返回一条 user 视角的元数据；这样 LLM 可见的技能列表不会重复。
        """
        cache_key = user_id or ""
        now = time.monotonic()
        cached = self._skill_cache.get(cache_key)
        if cached and now < cached.expires_at:
            return list(cached.skills)

        fingerprint = self._catalog_fingerprint(user_id=user_id)
        if cached and cached.fingerprint == fingerprint:
            cached.expires_at = now + SKILL_CACHE_TTL_SEC
            return list(cached.skills)

        system_skills = self._scan_dir(self.system_dir, owner_type="system")
        user_skills: List[SkillMeta] = []
        if user_id:
            user_skills = self._scan_dir(
                self.user_private_dir(user_id),
                owner_type="user",
                owner_user_id=user_id,
            )
        # 用户私有覆盖同名系统技能
        user_ids = {s.id for s in user_skills}
        merged = [s for s in system_skills if s.id not in user_ids] + user_skills
        merged.sort(key=lambda s: s.id)
        self._skill_cache[cache_key] = _SkillCacheEntry(
            skills=tuple(merged),
            fingerprint=fingerprint,
            expires_at=now + SKILL_CACHE_TTL_SEC,
        )
        if cached is not None:
            self._on_catalog_changed(user_id)
        logger.info(
            "刷新技能缓存: %d 个 (system=%d, user=%d, user_id=%s)",
            len(merged),
            len(system_skills),
            len(user_skills),
            user_id,
        )
        return merged

    def _on_catalog_changed(self, user_id: Optional[str]) -> None:
        """Runtime hook; the catalog itself does not own SDK sessions."""

    def get_skill(self, skill_id: str, *, user_id: Optional[str] = None) -> SkillMeta:
        """按 slug 获取技能。优先 users/<uid>/<id>，回退 system/<id>。"""
        if user_id:
            user_dir = self.user_private_dir(user_id) / skill_id
            if (user_dir / "SKILL.md").exists():
                return self._load_skill(user_dir, owner_type="user", owner_user_id=user_id)
        sys_dir = self.system_dir / skill_id
        if (sys_dir / "SKILL.md").exists():
            return self._load_skill(sys_dir, owner_type="system")
        raise FileNotFoundError(f"技能不存在: {skill_id}")

    def _load_skill(
        self,
        skill_dir: Path,
        *,
        owner_type: str = "system",
        owner_user_id: Optional[str] = None,
    ) -> SkillMeta:
        """从目录中的 SKILL.md 加载技能元数据"""
        skill_md = skill_dir / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")
        meta, _body = _parse_frontmatter(content)

        skill_id = skill_dir.name
        name = meta.get("name", skill_id)

        # description：frontmatter 中的值，否则取正文前 200 字符
        description = meta.get("description") or _body[:200].strip()

        # allowed_tools：YAML list 或逗号分隔字符串，否则取默认值
        raw_tools = meta.get("allowed_tools") or meta.get("allowed-tools")
        if isinstance(raw_tools, list):
            allowed_tools = [str(t) for t in raw_tools]
        elif isinstance(raw_tools, str) and raw_tools:
            allowed_tools = [t.strip() for t in raw_tools.split(",") if t.strip()]
        else:
            allowed_tools = list(DEFAULT_ALLOWED_TOOLS)

        stat = skill_md.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        return SkillMeta(
            id=skill_id,
            name=name,
            description=description,
            allowed_tools=allowed_tools,
            content=content,
            skill_dir=skill_dir,
            created_at=mtime,
            updated_at=mtime,
            is_system=(owner_type == "system"),
            owner_type=owner_type,
            owner_user_id=owner_user_id,
            user_id=owner_user_id,
        )

    def _build_skills_index(self, *, user_id: Optional[str] = None) -> str:
        """兼容无 session 的后台任务，构建旧式技能索引文本。

        SKILL.md 路径必须是绝对路径——agent cwd 会被切到 session 工作区，相对路径会失效。
        合并 system 区与该用户私有区；同 id 时私有覆盖。
        """
        skills = self.scan_skills(user_id=user_id)
        if not skills:
            return "（当前没有可用技能）"
        lines = []
        for s in skills:
            abs_path = (s.skill_dir / "SKILL.md").resolve()
            scope = "私有" if s.owner_type == "user" else "系统"
            lines.append(
                f"- **{s.id}** [{scope}]: {s.description}\n  SKILL.md 绝对路径: `{abs_path}`"
            )
        return "\n".join(lines)

    def _materialize_native_skills(
        self, cwd: Path, *, user_id: Optional[str]
    ) -> tuple[tuple[Any, ...], int]:
        """把当前用户可见技能映射到 session 的原生 `.claude/skills/`。

        Eido 的物理布局是 `system/<id>` 与 `users/<uid>/<id>`，而 Claude Code
        原生发现要求 `.claude/skills/<id>`。这里仅创建目录符号链接，不复制技能，
        因而 supporting files 与更新会立即可见；manifest 只用于安全清理本服务创建
        的旧链接，不会删除用户自行创建的普通目录。
        """
        skills = self.scan_skills(user_id=user_id)
        claude_dir = cwd / ".claude"
        native_root = claude_dir / "skills"
        claude_dir.mkdir(parents=True, exist_ok=True)
        native_root.mkdir(parents=True, exist_ok=True)
        manifest_path = claude_dir / _NATIVE_SKILLS_MANIFEST

        managed: dict[str, str] = {}
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                managed = {
                    str(name): str(target)
                    for name, target in raw.items()
                    if isinstance(name, str) and isinstance(target, str)
                }
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass

        expected: dict[str, str] = {}
        revision: list[tuple[Any, ...]] = []
        for skill in skills:
            if Path(skill.id).name != skill.id or skill.id in {"", ".", ".."}:
                logger.warning("跳过无法映射到原生目录的技能 ID: %r", skill.id)
                continue
            target = skill.skill_dir.resolve()
            expected[skill.id] = str(target)
            revision.append(
                (
                    skill.id,
                    str(target),
                    skill.updated_at,
                    len(skill.content),
                    skill.owner_type,
                )
            )

        revision_tuple = tuple(revision)
        view_key = str(cwd.resolve())
        previous_view = self._native_skill_views.get(view_key)
        if previous_view and previous_view[0] == revision_tuple and manifest_path.is_file():
            return previous_view

        for name, old_target in managed.items():
            if expected.get(name) == old_target:
                continue
            link = native_root / name
            if link.is_symlink():
                try:
                    current = (link.parent / os.readlink(link)).resolve()
                    if str(current) == old_target:
                        link.unlink()
                except OSError:
                    logger.warning("清理旧技能链接失败: %s", link, exc_info=True)

        installed: dict[str, str] = {}
        for name, target_text in expected.items():
            link = native_root / name
            target = Path(target_text)
            if link.is_symlink():
                try:
                    current = (link.parent / os.readlink(link)).resolve()
                    if current != target:
                        link.unlink()
                        link.symlink_to(target, target_is_directory=True)
                except OSError:
                    logger.warning("更新技能链接失败: %s", link, exc_info=True)
                    continue
            elif link.exists():
                logger.warning("原生技能路径已存在且非托管链接，保留并跳过: %s", link)
                continue
            else:
                try:
                    link.symlink_to(target, target_is_directory=True)
                except OSError:
                    logger.warning("创建技能链接失败: %s -> %s", link, target, exc_info=True)
                    continue
            installed[name] = target_text

        if managed != installed or not manifest_path.exists():
            manifest_path.write_text(
                json.dumps(installed, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        result = (revision_tuple, len(installed))
        self._native_skill_views[view_key] = result
        return result
