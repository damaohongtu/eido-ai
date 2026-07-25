"""
基于本地文件的技能服务

技能定义维护在 .claude/skills/ 目录下的 SKILL.md 文件中，
通过 claude_agent_sdk 自动规划执行，无需数据库。
用户请求无需携带 skill_id，由 claude_agent_sdk 从用户输入中自动选择并执行技能。

目录布局：
  $SKILLS_DIR/
    system/<id>/SKILL.md          # admin 上传/内置，所有用户只读可见
    users/<safe_user_id>/<id>/    # 用户私有，仅本人可改

权限通过路径区分：在 system/ 下即系统技能；在 users/<uid>/ 下即该用户私有。
"""
import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, List, Optional
from urllib.parse import urlsplit

from app.gateway.sandbox_manager import _safe_user_id
from app.services.conversation_context import format_recent_conversation
from app.services.project_context import ProjectContext, format_project_context

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_TOOLS = ["Bash", "Glob", "Read", "WebFetch"]

# SSE 心跳：长任务（例如 Bash 60s+）期间持续向客户端注入 ": ping" 注释帧，
# 防止 Vite dev proxy / 浏览器 fetch 在长时间无数据时丢弃连接抛 TypeError。
# 注释行不带 `data: ` 前缀，前端 SSE 解析逻辑会自然忽略。
HEARTBEAT_INTERVAL_SEC = 12.0
_HEARTBEAT_FRAME = ": ping\n\n"

# 技能列表 API 会在页面装载期间被并发请求多次。缓存命中时不再遍历/解析
# SKILL.md；TTL 到期后先比较轻量 stat 指纹，内容未变则继续复用对象。
SKILL_CACHE_TTL_SEC = 5.0

# ClaudeSDKClient 复用同一个 Claude Code 子进程，避免每轮重新启动、扫描技能、
# 初始化工具。最大存活时间还会受 EIDO_USER_TOKEN_TTL 约束。
CLIENT_IDLE_TTL_SEC = 15 * 60.0
CLIENT_POOL_MAX = 32

_NATIVE_SKILLS_MANIFEST = ".eido-native-skills.json"

# 历史标记文件：保留以兼容旧目录扫描，不再作为权限判定依据
USER_UPLOAD_MARKER = ".eido-user-upload"

SYSTEM_SUBDIR = "system"
USERS_SUBDIR = "users"


def _serialize_log_value(value: object) -> str:
    """Serialize complete log payloads without letting unusual SDK values break a run."""
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError, RecursionError):
        return repr(value)


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
    body = content[end + 4:].lstrip("\n")

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
    id: str                        # 目录名，即 slug，如 financial-report-analyst
    name: str
    description: str
    allowed_tools: List[str]
    content: str                   # SKILL.md 完整原文
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


@dataclass
class _ClaudeClientEntry:
    client: Any
    key: tuple[str, str]
    user_id: Optional[str]
    signature: tuple[Any, ...]
    created_at: float
    last_used: float
    busy: bool = True
    stale: bool = False


class _ResumeUnavailable(RuntimeError):
    """原生会话在产生本轮输出前已不可恢复，可安全回退到重建模式。"""

    def __init__(self, cause: Exception):
        super().__init__(str(cause))
        self.cause = cause


class _AgentAuthenticationError(RuntimeError):
    """Agent SDK could not use a supported non-interactive credential."""


class ClaudeSkillService:
    """基于本地文件的技能服务"""

    def __init__(self, skills_dir: Path, workspace_root: Path):
        self.skills_dir = skills_dir
        self.workspace_root = workspace_root
        self._skill_cache: dict[str, _SkillCacheEntry] = {}
        self._native_skill_views: dict[str, tuple[tuple[Any, ...], int]] = {}
        self._clients: dict[tuple[str, str], _ClaudeClientEntry] = {}
        self._client_cleanup_tasks: set[asyncio.Task] = set()

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
        for entry in self._clients.values():
            if affected_user is None or entry.user_id == affected_user:
                entry.stale = True

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
            for entry in self._clients.values():
                if entry.user_id == user_id:
                    entry.stale = True
        logger.info(
            "刷新技能缓存: %d 个 (system=%d, user=%d, user_id=%s)",
            len(merged),
            len(system_skills),
            len(user_skills),
            user_id,
        )
        return merged

    def get_skill(self, skill_id: str, *, user_id: Optional[str] = None) -> SkillMeta:
        """按 slug 获取技能。优先 users/<uid>/<id>，回退 system/<id>。"""
        if user_id:
            user_dir = self.user_private_dir(user_id) / skill_id
            if (user_dir / "SKILL.md").exists():
                return self._load_skill(
                    user_dir, owner_type="user", owner_user_id=user_id
                )
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

    # ------------------------------------------------------------------ #
    #  技能执行                                                             #
    # ------------------------------------------------------------------ #

    # 自动执行模式下使用的通用工具集（覆盖所有技能可能需要的工具）
    AUTO_ALLOWED_TOOLS = [
        "Bash",
        "Glob",
        "Grep",
        "Read",
        "Write",
        "Edit",
        "WebFetch",
        "WebSearch",
    ]

    @staticmethod
    def _extract_latest_user_text(messages: list) -> str:
        """从消息列表尾部找出最后一条 user 消息文本。

        切换到原生 resume 后，对话历史由 Claude Code 自己的 jsonl 维护，
        后端不再重复重建历史，prompt 只携带"本轮最新一条 user 输入"。
        """
        def _role(m: object) -> str:
            return (
                getattr(m, "role", None)
                or (m.get("role") if isinstance(m, dict) else "")
                or ""
            )

        def _content(m: object) -> str:
            c = (
                getattr(m, "content", None)
                if not isinstance(m, dict)
                else m.get("content")
            )
            return (c or "").strip()

        for msg in reversed(messages or []):
            if _role(msg) == "user":
                return _content(msg)
        return ""

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

    @staticmethod
    def _client_key(user_id: Optional[str], session_id: str) -> tuple[str, str]:
        return (user_id or "", session_id)

    @staticmethod
    def _client_max_age_sec() -> float:
        """复用连接不能超过短期 EIDO_USER_TOKEN 的有效期。"""
        try:
            from app.core.config import settings

            token_ttl = float(settings.EIDO_USER_TOKEN_TTL)
        except Exception:
            token_ttl = 300.0
        return max(0.0, min(CLIENT_IDLE_TTL_SEC, token_ttl - 30.0))

    async def _close_client_entry(self, entry: _ClaudeClientEntry) -> None:
        try:
            await entry.client.disconnect()
        except Exception:
            logger.debug("关闭 ClaudeSDKClient 失败", exc_info=True)

    def _schedule_client_close(self, entry: _ClaudeClientEntry) -> None:
        try:
            task = asyncio.create_task(self._close_client_entry(entry))
        except RuntimeError:
            return
        self._client_cleanup_tasks.add(task)
        task.add_done_callback(self._client_cleanup_tasks.discard)

    async def _prune_clients(self) -> None:
        now = time.monotonic()
        stale: list[_ClaudeClientEntry] = []
        max_age = self._client_max_age_sec()
        for key, entry in list(self._clients.items()):
            if entry.busy:
                continue
            if (
                entry.stale
                or now - entry.last_used > CLIENT_IDLE_TTL_SEC
                or max_age <= 0
                or now - entry.created_at > max_age
            ):
                if self._clients.pop(key, None) is entry:
                    stale.append(entry)
        for entry in stale:
            await self._close_client_entry(entry)

    async def _acquire_client(
        self,
        *,
        options: Any,
        user_id: Optional[str],
        session_id: str,
        signature: tuple[Any, ...],
    ) -> tuple[_ClaudeClientEntry, bool, float]:
        """获取 session 级长连接；返回 (entry, warm_hit, connect_ms)。"""
        from claude_agent_sdk import ClaudeSDKClient  # type: ignore

        await self._prune_clients()
        key = self._client_key(user_id, session_id)
        now = time.monotonic()
        current = self._clients.get(key)
        max_age = self._client_max_age_sec()
        if (
            current
            and not current.busy
            and not current.stale
            and current.signature == signature
            and max_age > 0
            and now - current.created_at <= max_age
        ):
            current.busy = True
            return current, True, 0.0

        if current is not None:
            if current.busy:
                raise RuntimeError(f"Claude session 正在执行: {session_id}")
            self._clients.pop(key, None)
            await self._close_client_entry(current)

        started = time.perf_counter()
        client = ClaudeSDKClient(options=options)
        await client.connect()
        connect_ms = (time.perf_counter() - started) * 1000
        now = time.monotonic()
        entry = _ClaudeClientEntry(
            client=client,
            key=key,
            user_id=user_id,
            signature=signature,
            created_at=now,
            last_used=now,
        )
        self._clients[key] = entry

        if len(self._clients) > CLIENT_POOL_MAX:
            candidates = sorted(
                (
                    item
                    for item in self._clients.values()
                    if not item.busy and item is not entry
                ),
                key=lambda item: item.last_used,
            )
            while len(self._clients) > CLIENT_POOL_MAX and candidates:
                victim = candidates.pop(0)
                if self._clients.pop(victim.key, None) is victim:
                    self._schedule_client_close(victim)
        return entry, False, connect_ms

    async def _release_client(
        self, entry: _ClaudeClientEntry, *, healthy: bool
    ) -> None:
        entry.busy = False
        entry.last_used = time.monotonic()
        if not healthy or entry.stale:
            if self._clients.pop(entry.key, None) is entry:
                await self._close_client_entry(entry)

    def reset_session(self, session_id: str) -> None:
        """驱逐指定 Eido session 的长连接；供项目切换/删除时调用。"""
        for path in list(self._native_skill_views):
            if Path(path).name == session_id:
                self._native_skill_views.pop(path, None)
        for key, entry in list(self._clients.items()):
            if key[1] != session_id:
                continue
            entry.stale = True
            if not entry.busy and self._clients.pop(key, None) is entry:
                self._schedule_client_close(entry)

    async def shutdown(self) -> None:
        """应用关闭时回收所有 Claude Code 子进程。"""
        entries = list(self._clients.values())
        self._clients.clear()
        if entries:
            await asyncio.gather(
                *(self._close_client_entry(entry) for entry in entries),
                return_exceptions=True,
            )
        if self._client_cleanup_tasks:
            await asyncio.gather(*tuple(self._client_cleanup_tasks), return_exceptions=True)

    async def execute_stream(
        self, messages: list, context: Optional[str] = None,
        *, user_id: Optional[str] = None, session_id: Optional[str] = None,
        project_context: Optional[ProjectContext] = None,
    ) -> AsyncGenerator[str, None]:
        """通过 claude_agent_sdk 自动规划执行，以 SSE 格式流式返回。

        架构要点：
        - 使用 Claude Code 原生 `resume` 续接：每个 eido 会话首轮跑出 claude_session_id
          后落盘到 chat_sessions.claude_session_id；后续轮次只需 resume，
          prompt 仅携带本轮最新一条 user 消息（历史/记忆由 Claude Code 自己的 jsonl 管）。
        - SSE 心跳：长任务期间每 ~12s 推一个注释帧，防止前端 fetch 在静默期断连。
        - resume 失败时（claude jsonl 缺失/损坏）自动清掉旧 sid，回退到首轮模式重跑。

        messages    完整对话历史（仅本轮最新一条 user 真正进入 prompt）。
        context     多技能流水线中上一步的输出，附加在 prompt 末尾。
        user_id     当前用户 ID，用于生成 agent 子进程的身份 token。
        session_id  会话 ID。指定后 agent cwd 切到该会话工作区（强隔离）；
                    未指定则回退到全局 workspace_root（兼容历史路径）。
        """
        logger.info(
            f"▶ execute_stream 开始 | 消息数: {len(messages)}"
            + (f" | session={session_id}" if session_id else "")
            + (f" | 含上下文 {len(context)} 字符" if context else "")
        )

        yield self._sse({"type": "thinking", "content": "正在分析请求，自动规划执行..."})
        yield self._sse({"type": "workflow_start", "skill_name": "auto"})

        # 解析 cwd（按 session 隔离时使用 session 工作区）
        if session_id:
            from app.services.session_workspace import get_session_workspace_manager
            try:
                cwd = get_session_workspace_manager().session_root(session_id)
            except ValueError as e:
                yield self._sse({"type": "error", "message": f"非法 session_id: {e}"})
                yield "data: [DONE]\n\n"
                return
        else:
            cwd = self.workspace_root

        native_skills = bool(session_id)
        skill_revision: tuple[Any, ...] = ()
        skill_count = 0
        if native_skills:
            try:
                skill_revision, skill_count = self._materialize_native_skills(
                    cwd, user_id=user_id
                )
            except Exception:
                logger.exception("原生技能映射失败，回退到兼容技能索引")
                native_skills = False

        # 导入 SDK
        try:
            from claude_agent_sdk import (  # type: ignore
                ClaudeAgentOptions,
                ClaudeSDKError,
                query,
            )
        except ImportError:
            logger.error("claude_agent_sdk 未安装")
            yield self._sse({
                "type": "error",
                "message": "claude_agent_sdk 未安装，请运行: pip install claude-agent-sdk"
            })
            yield "data: [DONE]\n\n"
            return

        latest_user_text = self._extract_latest_user_text(messages)
        if not latest_user_text:
            yield self._sse({"type": "error", "message": "未找到用户输入"})
            yield "data: [DONE]\n\n"
            return
        claude_sid = self._load_claude_sid(
            user_id, session_id, project_context=project_context
        )
        agent_env = self._build_agent_env(
            user_id, session_id, project_context.id if project_context else None
        )
        auth_error = self._agent_auth_error(agent_env)
        if auth_error:
            logger.error("Claude Agent SDK 认证配置缺失: %s", auth_error)
            yield self._sse({"type": "error", "message": auth_error})
            yield "data: [DONE]\n\n"
            return
        auth_mode, provider = self._agent_auth_summary(agent_env)
        logger.info("  [ClaudeAuth] mode=%s provider=%s", auth_mode, provider)
        project_signature = (
            project_context.id,
            project_context.context_revision,
        ) if project_context else (None, None)
        client_signature = (str(cwd.resolve()), project_signature, skill_revision)

        async def _run_once(resume_sid: Optional[str]) -> AsyncGenerator[str, None]:
            """单次 SDK 调用，按 resume 模式构建不同 prompt/options。"""
            prompt = self._build_prompt(
                cwd=cwd,
                latest_user_text=latest_user_text,
                context=context,
                user_id=user_id,
                resume=bool(resume_sid),
                project_context=project_context,
                conversation_history=(
                    format_recent_conversation(messages) if not resume_sid else ""
                ),
                native_skills=native_skills,
            )
            available_tools = list(self.AUTO_ALLOWED_TOOLS)
            if native_skills:
                available_tools.append("Skill")
            options = ClaudeAgentOptions(
                allowed_tools=self.AUTO_ALLOWED_TOOLS,
                tools=available_tools,
                cwd=str(cwd),
                setting_sources=["project"] if native_skills else [],
                skills="all" if native_skills else None,
                permission_mode="acceptEdits",
                env=agent_env,
                include_partial_messages=False,
                max_buffer_size=10 * 1024 * 1024,
                resume=resume_sid,
            )
            entry: Optional[_ClaudeClientEntry] = None
            warm_hit = False
            connect_ms = 0.0
            message_seen = False
            saw_result = False
            run_started = time.perf_counter()
            try:
                if session_id:
                    try:
                        entry, warm_hit, connect_ms = await self._acquire_client(
                            options=options,
                            user_id=user_id,
                            session_id=session_id,
                            signature=client_signature,
                        )
                        await entry.client.query(prompt)
                    except ClaudeSDKError as exc:
                        if resume_sid:
                            raise _ResumeUnavailable(exc) from exc
                        raise
                    messages_iter = entry.client.receive_response()
                else:
                    messages_iter = query(prompt=prompt, options=options)

                logger.info(
                    "  [ClaudeRun] mode=%s warm=%s connect_ms=%.1f prompt_chars=%d "
                    "skills=%d tools=%d cwd=%s",
                    "resume" if resume_sid else "fresh",
                    warm_hit,
                    connect_ms,
                    len(prompt),
                    skill_count,
                    len(available_tools),
                    cwd,
                )

                async for message in messages_iter:
                    if not message_seen:
                        logger.info(
                            "  [ClaudeRun] first_message_ms=%.1f warm=%s session=%s",
                            (time.perf_counter() - run_started) * 1000,
                            warm_hit,
                            session_id or "(none)",
                        )
                    message_seen = True
                    self._log_message(message)
                    if self._is_not_logged_in_message(message):
                        raise _AgentAuthenticationError(
                            self._agent_auth_failure_message()
                        )
                    # 捕获原生 session_id，持久化以便进程回收/服务重启后 resume
                    try:
                        from claude_agent_sdk.types import ResultMessage  # type: ignore
                        if isinstance(message, ResultMessage):
                            saw_result = True
                            if session_id and getattr(message, "session_id", None):
                                self._save_claude_sid(
                                    user_id,
                                    session_id,
                                    message.session_id,
                                    project_context=project_context,
                                )
                    except Exception as e:
                        logger.warning(f"持久化 claude_session_id 失败: {e}")
                    for event in self._convert_message(message):
                        yield event
            except ClaudeSDKError as exc:
                if resume_sid and not message_seen:
                    raise _ResumeUnavailable(exc) from exc
                raise
            finally:
                if entry is not None:
                    await self._release_client(entry, healthy=saw_result)

        # ---- 生产者 + 心跳 桥接到外层 yield ----
        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        # 标志：是否发生过 error 事件，决定结束时是否再发 workflow_complete
        had_error = {"v": False}

        async def producer() -> None:
            tried_resume = bool(claude_sid)
            try:
                if tried_resume:
                    try:
                        async for ev in _run_once(claude_sid):
                            await queue.put(ev)
                        return
                    except _ResumeUnavailable as e:
                        cause = e.cause
                        logger.warning(
                            "resume(%s) 在本轮输出前失败，清 sid 并回退到重建模式: %s",
                            claude_sid,
                            cause,
                        )
                        if session_id:
                            self._save_claude_sid(
                                user_id,
                                session_id,
                                None,
                                project_context=project_context,
                            )
                        await queue.put(
                            self._sse({"type": "thinking", "content": "原会话已失效，重建中..."})
                        )
                    except Exception as e:
                        logger.error(f"resume 模式执行异常: {e}", exc_info=True)
                        had_error["v"] = True
                        await queue.put(self._sse({"type": "error", "message": f"执行失败: {e}"}))
                        return
                async for ev in _run_once(None):
                    await queue.put(ev)
            except asyncio.CancelledError:
                raise
            except _AgentAuthenticationError as e:
                logger.error("Claude Agent SDK 认证失败: %s", e)
                had_error["v"] = True
                await queue.put(self._sse({"type": "error", "message": str(e)}))
            except Exception as e:
                logger.error(f"技能自动执行失败: {e}", exc_info=True)
                had_error["v"] = True
                await queue.put(self._sse({"type": "error", "message": f"执行失败: {e}"}))
            finally:
                await queue.put(_SENTINEL)

        async def heartbeat() -> None:
            try:
                while True:
                    await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
                    await queue.put(_HEARTBEAT_FRAME)
            except asyncio.CancelledError:
                pass

        prod_task = asyncio.create_task(producer())
        hb_task = asyncio.create_task(heartbeat())

        try:
            while True:
                ev = await queue.get()
                if ev is _SENTINEL:
                    break
                yield ev
            if not had_error["v"]:
                yield self._sse({"type": "workflow_complete", "data": {"references": []}})
            logger.info("◀ execute_stream 完成")
        finally:
            hb_task.cancel()
            if not prod_task.done():
                prod_task.cancel()
            # 让被 cancel 的任务有机会清理
            for t in (hb_task, prod_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

        yield "data: [DONE]\n\n"

    # ------------------------------------------------------------------ #
    #  prompt / options 辅助                                                #
    # ------------------------------------------------------------------ #

    def _build_prompt(
        self,
        *,
        cwd: Path,
        latest_user_text: str,
        context: Optional[str],
        user_id: Optional[str],
        resume: bool,
        project_context: Optional[ProjectContext] = None,
        conversation_history: str = "",
        native_skills: bool = False,
    ) -> str:
        """根据是否 resume 构造 prompt：
        - 首轮：workspace/project/重建历史 + 本轮输入；session 使用原生 Skills
        - 续接：仅本轮输入 + 流水线上下文；历史和项目上下文均由原生会话维护
        """
        context_section = ""
        if context and context.strip():
            truncated = context.strip()[:4000]
            context_section = (
                f"\n\n---\n\n## 上一步执行结果（供参考）\n\n{truncated}\n"
            )

        if resume:
            # Project revision 变化会先清 provider SID，因此续接时无需重复注入
            # 最多 20k+ 的项目说明/文件表；这部分已存在于原生 transcript。
            return f"## 用户最新请求\n\n{latest_user_text}{context_section}"

        project_text = format_project_context(project_context)
        project_section = f"{project_text}\n\n---\n\n" if project_text else ""
        history_section = (
            f"{conversation_history}\n\n---\n\n" if conversation_history else ""
        )

        skills_root_abs = Path(self.skills_dir).resolve()
        workspace_section = (
            f"**当前会话工作区（你的 cwd）**: `{cwd}`\n"
            f"  - 用户上传文件位于: `{cwd / 'uploads'}`\n"
            f"  - 你生成的所有产物请写入: `{cwd / 'outputs'}`\n"
            f"**技能库根目录（绝对路径，仅可读取）**: `{skills_root_abs}`\n"
        )
        if native_skills:
            skills_section = (
                "## 技能使用\n\n"
                "可用技能已由 Claude Code 原生 Skills 机制注册。根据请求按需调用 Skill；"
                "技能正文会在命中后加载，无需先读取或枚举 SKILL.md。\n\n---\n\n"
            )
        else:
            skills_index = self._build_skills_index(user_id=user_id)
            skills_section = (
                f"## 可用技能列表\n\n{skills_index}\n\n---\n\n"
                "## 技能使用\n\n根据最新请求选择技能，并用 Read 读取对应 SKILL.md 的绝对路径。\n\n"
                "---\n\n"
            )
        return (
            f"{workspace_section}\n"
            f"{project_section}"
            f"{skills_section}"
            f"## 执行说明\n\n"
            f"- 所有写文件操作请落在 `{cwd / 'outputs'}` 目录下；不要写到工作区之外。\n"
            f"- 用户上传文件已在消息中提供绝对路径，可直接 Read。\n"
            f"- 技能库只读；不要修改 `.claude/skills` 或技能源目录。\n"
            f"- 所有环境变量均已配置（包括 EIDO_USER_TOKEN），无需手动 export。\n\n"
            f"---\n\n"
            f"{history_section}"
            f"## 用户最新请求\n\n{latest_user_text}"
            f"{context_section}"
        )

    @staticmethod
    def _build_agent_env(
        user_id: Optional[str], session_id: Optional[str], project_id: Optional[str] = None
    ) -> dict:
        from app.core.config import settings

        # 多租户 session 不应读取宿主机 ~/.claude/projects 的自动记忆；关闭它也
        # 避免每个冷启动把无关 memory 重复塞入 system prompt。
        # Provider 配置来自 Settings，而不是依赖父进程 export。这样
        # backend/.env 中的 API key/base URL 会被确定性传给 SDK 内置 CLI。
        env: dict[str, str] = {
            **settings.claude_agent_env,
            "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
        }
        if user_id:
            from app.core.user_token import create_user_token
            env["EIDO_USER_TOKEN"] = create_user_token(user_id)
        if session_id:
            env["EIDO_SESSION_ID"] = session_id
        if project_id:
            env["EIDO_PROJECT_ID"] = project_id
        return env

    @staticmethod
    def _agent_auth_error(agent_env: dict[str, str]) -> Optional[str]:
        credential_keys = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
        provider_flags = (
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_ANTHROPIC_AWS",
            "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY",
        )
        if any(agent_env.get(key) for key in (*credential_keys, *provider_flags)):
            return None
        return ClaudeSkillService._agent_auth_failure_message()

    @staticmethod
    def _agent_auth_failure_message() -> str:
        return (
            "Claude Agent SDK 未配置可用的非交互式凭据。请在 backend/.env "
            "配置 Claude Console 的 ANTHROPIC_API_KEY（推荐），或配置受支持的 "
            "Anthropic 兼容网关/云平台凭据，然后重启后端。Claude.ai 的 /login "
            "登录不能作为 Eido Agent SDK 的认证方式。"
        )

    @staticmethod
    def _agent_auth_summary(agent_env: dict[str, str]) -> tuple[str, str]:
        if agent_env.get("ANTHROPIC_API_KEY"):
            auth_mode = "api_key"
        elif agent_env.get("ANTHROPIC_AUTH_TOKEN"):
            auth_mode = "auth_token"
        else:
            auth_mode = next(
                (
                    key.removeprefix("CLAUDE_CODE_USE_").lower()
                    for key in (
                        "CLAUDE_CODE_USE_BEDROCK",
                        "CLAUDE_CODE_USE_ANTHROPIC_AWS",
                        "CLAUDE_CODE_USE_VERTEX",
                        "CLAUDE_CODE_USE_FOUNDRY",
                    )
                    if agent_env.get(key)
                ),
                "missing",
            )
        base_url = agent_env.get("ANTHROPIC_BASE_URL", "").strip()
        provider = urlsplit(base_url).hostname if base_url else "api.anthropic.com"
        return auth_mode, provider or "custom"

    @staticmethod
    def _is_not_logged_in_message(message: object) -> bool:
        try:
            from claude_agent_sdk.types import AssistantMessage, TextBlock  # type: ignore
        except ImportError:
            return False
        if not isinstance(message, AssistantMessage):
            return False
        return any(
            isinstance(block, TextBlock)
            and "not logged in" in block.text.lower()
            and "/login" in block.text.lower()
            for block in message.content
        )

    @staticmethod
    def _load_claude_sid(
        user_id: Optional[str],
        session_id: Optional[str],
        *,
        project_context: Optional[ProjectContext],
    ) -> Optional[str]:
        if not (user_id and session_id):
            return None
        try:
            from app.services.chat_session_store import get_chat_session_store
            return get_chat_session_store().get_claude_session_id(
                user_id,
                session_id,
                expected_project_id=project_context.id if project_context else None,
                expected_context_revision=(
                    project_context.context_revision if project_context else None
                ),
            )
        except Exception as e:
            logger.warning(f"读取 claude_session_id 失败: {e}")
            return None

    @staticmethod
    def _save_claude_sid(
        user_id: Optional[str],
        session_id: Optional[str],
        claude_sid: Optional[str],
        *,
        project_context: Optional[ProjectContext],
    ) -> None:
        if not (user_id and session_id):
            return
        from app.services.chat_session_store import get_chat_session_store
        saved = get_chat_session_store().set_claude_session_id(
            user_id,
            session_id,
            claude_sid,
            expected_project_id=project_context.id if project_context else None,
            expected_context_revision=(
                project_context.context_revision if project_context else None
            ),
        )
        if not saved:
            logger.info("忽略已过期请求返回的 Claude session ID: session=%s", session_id)

    # ------------------------------------------------------------------ #
    #  消息转换                                                             #
    # ------------------------------------------------------------------ #

    def _log_message(self, message: object) -> None:
        """将完整 SDK 消息写入日志，便于按 traceId 追踪执行过程。"""
        try:
            from claude_agent_sdk.types import (  # type: ignore
                AssistantMessage,
                ResultMessage,
                SystemMessage,
                TextBlock,
                ThinkingBlock,
                ToolResultBlock,
                ToolUseBlock,
                UserMessage,
            )
        except ImportError:
            return

        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    logger.info(
                        "  [Assistant/Text] %s",
                        _serialize_log_value(block.text),
                    )
                elif isinstance(block, ThinkingBlock):
                    logger.debug(
                        "  [Assistant/Thinking] %s",
                        _serialize_log_value(block.thinking),
                    )
                elif isinstance(block, ToolUseBlock):
                    logger.info(
                        "  [Tool/Call] %s | 参数: %s",
                        block.name,
                        _serialize_log_value(block.input),
                    )

        elif isinstance(message, UserMessage):
            if isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        raw = block.content
                        content_str = raw if isinstance(raw, str) else str(raw or "")
                        status = "ERROR" if block.is_error else "OK"
                        logger.info(
                            "  [Tool/Result:%s] %s",
                            status,
                            _serialize_log_value(content_str),
                        )

        elif isinstance(message, SystemMessage):
            logger.info(
                "  [System/%s] %s",
                message.subtype,
                _serialize_log_value(message.data),
            )

        elif isinstance(message, ResultMessage):
            cost = f"${message.total_cost_usd:.4f}" if message.total_cost_usd else "N/A"
            duration = f"{message.duration_ms / 1000:.1f}s"
            status = "ERROR" if message.is_error else "OK"
            usage = message.usage or {}
            logger.info(
                f"  [Result/{status}] 用时={duration} | 费用={cost} | "
                f"轮次={message.num_turns} | session={message.session_id} | "
                f"terminal={getattr(message, 'terminal_reason', None) or '-'} | "
                f"api_status={getattr(message, 'api_error_status', None) or '-'} | "
                f"input={usage.get('input_tokens', 0)} | "
                f"cache_read={usage.get('cache_read_input_tokens', 0)} | "
                f"cache_create={usage.get('cache_creation_input_tokens', 0)} | "
                f"output={usage.get('output_tokens', 0)}"
            )

    def _convert_message(self, message: object) -> List[str]:
        """将 claude_agent_sdk 消息转换为前端 SSE 事件列表。

        SDK 返回强类型 dataclass，必须用 isinstance 判断，不能依赖 type 属性。
        消息类型：AssistantMessage / UserMessage / SystemMessage / ResultMessage / StreamEvent
        """
        try:
            from claude_agent_sdk.types import (  # type: ignore
                AssistantMessage,
                ResultMessage,
                SystemMessage,
                TextBlock,
                ThinkingBlock,
                ToolResultBlock,
                ToolUseBlock,
                UserMessage,
            )
        except ImportError:
            return []

        events: List[str] = []

        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    if block.text:
                        events.append(self._sse({"type": "content", "content": block.text}))
                elif isinstance(block, ThinkingBlock):
                    preview = block.thinking[:300].strip()
                    if preview:
                        events.append(self._sse({
                            "type": "thinking",
                            "content": f"[深度思考] {preview}{'…' if len(block.thinking) > 300 else ''}"
                        }))
                elif isinstance(block, ToolUseBlock):
                    hint = self._tool_hint(block.name, block.input)
                    events.append(self._sse({"type": "thinking", "content": hint}))

        elif isinstance(message, UserMessage):
            if isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        raw = block.content
                        content_str = raw if isinstance(raw, str) else (
                            str(raw) if raw is not None else ""
                        )
                        preview = content_str[:200].strip()
                        status = "✗ 工具出错" if block.is_error else "✓ 工具完成"
                        hint = f"{status}: {preview}" if preview else status
                        events.append(self._sse({"type": "thinking", "content": hint}))

        elif isinstance(message, SystemMessage):
            if message.subtype == "init":
                tools = message.data.get("tools", [])
                if tools:
                    tool_list = ", ".join(tools[:6]) + ("…" if len(tools) > 6 else "")
                    events.append(self._sse({
                        "type": "thinking",
                        "content": f"已加载工具: {tool_list}"
                    }))

        elif isinstance(message, ResultMessage):
            # 不重复发送 result：AssistantMessage 的 TextBlock 已包含完整回复，
            # ResultMessage.result 与之相同，再发会导致前端显示重复内容
            cost = f"${message.total_cost_usd:.4f}" if message.total_cost_usd else "N/A"
            duration = f"{message.duration_ms / 1000:.1f}s"
            events.append(self._sse({
                "type": "thinking",
                "content": (
                    f"执行完成 | 用时: {duration} | "
                    f"费用: {cost} | 轮次: {message.num_turns}"
                    + (" | ⚠️ 出错" if message.is_error else "")
                )
            }))

        return events

    def _tool_hint(self, tool_name: str, tool_input: dict) -> str:
        """根据工具名称和参数生成人类可读的思考提示"""
        hints = {
            "Read":      lambda i: f"读取文件: {i.get('file_path', '')}",
            "Bash":      lambda i: f"执行命令: {str(i.get('command', ''))[:120]}",
            "Glob":      lambda i: f"查找文件: {i.get('pattern', '')}",
            "WebFetch":  lambda i: f"获取网页: {i.get('url', '')}",
            "WebSearch": lambda i: f"搜索: {i.get('query', '')}",
            "Write":     lambda i: f"写入文件: {i.get('file_path', '')}",
            "Edit":      lambda i: f"编辑文件: {i.get('file_path', '')}",
            "Grep":      lambda i: f"搜索内容: {i.get('pattern', '')}",
            "MultiEdit": lambda i: f"批量编辑: {i.get('file_path', '')}",
            "Skill":     lambda i: f"加载技能: {i.get('skill', i.get('name', ''))}",
        }
        fn = hints.get(tool_name)
        if fn:
            try:
                return fn(tool_input)
            except Exception:
                pass
        return f"正在调用工具: {tool_name}..."

    # ------------------------------------------------------------------ #
    #  工具方法                                                             #
    # ------------------------------------------------------------------ #

    def _sse(self, data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ------------------------------------------------------------------ #
#  全局单例                                                             #
# ------------------------------------------------------------------ #

_instance: Optional[ClaudeSkillService] = None

# 保留此名称供旧代码兼容导入（始终为 None，请改用 get_claude_skill_service()）
claude_skill_service: Optional[ClaudeSkillService] = None


def get_claude_skill_service() -> Optional[ClaudeSkillService]:
    """获取全局单例，startup 完成后才非 None。"""
    return _instance


def init_claude_skill_service(
    skills_dir: Path, workspace_root: Path
) -> ClaudeSkillService:
    global _instance, claude_skill_service
    _instance = ClaudeSkillService(skills_dir, workspace_root)
    claude_skill_service = _instance          # 保持兼容
    logger.info(f"ClaudeSkillService 初始化完成 - 技能目录: {skills_dir}")
    return _instance
