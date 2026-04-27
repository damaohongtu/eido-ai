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
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, List, Optional

from app.gateway.sandbox_manager import _safe_user_id

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_TOOLS = ["Bash", "Glob", "Read", "WebFetch"]

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


class ClaudeSkillService:
    """基于本地文件的技能服务"""

    def __init__(self, skills_dir: Path, workspace_root: Path):
        self.skills_dir = skills_dir
        self.workspace_root = workspace_root

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

    def scan_skills(self, *, user_id: Optional[str] = None) -> List[SkillMeta]:
        """扫描 system 区 +（若给定 user_id）该用户私有区。

        合并策略：同 id 在 user 私有与 system 中都存在时，user 区覆盖 system 区，
        仅返回一条 user 视角的元数据；这样 LLM 可见的技能列表不会重复。
        """
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
        logger.info(
            "扫描到 %d 个技能 (system=%d, user=%d, user_id=%s)",
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
        raw_tools = meta.get("allowed_tools")
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
    AUTO_ALLOWED_TOOLS = ["Bash", "Glob", "Read", "Write", "Edit", "WebFetch"]

    @staticmethod
    def _format_messages(messages: list) -> str:
        """将对话历史格式化为 prompt 文本块，一次性传给 claude_agent_sdk。

        策略：
        - system 消息跳过
        - 最近 6 条消息保留完整内容
        - 更早的 assistant 消息截断到 300 字符（减少 token），user 消息保留完整
        - 超过 30 条时只保留最近 30 条，避免 prompt 过长
        """
        role_label = {"user": "用户", "assistant": "助手"}

        filtered = [
            m for m in messages
            if (getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else "user")) != "system"
        ]

        if len(filtered) > 30:
            filtered = filtered[-30:]

        recent_threshold = max(0, len(filtered) - 6)
        lines: List[str] = []

        for i, msg in enumerate(filtered):
            role = getattr(msg, "role", msg.get("role") if isinstance(msg, dict) else "user")
            content = getattr(msg, "content", msg.get("content") if isinstance(msg, dict) else "")
            label = role_label.get(role, role)
            body = content.strip()

            is_recent = i >= recent_threshold
            if role == "assistant" and not is_recent:
                body = body[:300] + ("…（已截断）" if len(body) > 300 else "")

            lines.append(f"**{label}**: {body}")

        return "\n\n".join(lines)

    def _build_skills_index(self, *, user_id: Optional[str] = None) -> str:
        """构建可用技能索引文本，用于告知 Claude 有哪些技能可以使用。

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

    async def execute_stream(
        self, messages: list, context: Optional[str] = None,
        *, user_id: Optional[str] = None, session_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """通过 claude_agent_sdk 自动规划执行，以 SSE 格式流式返回。

        无需指定 skill_id，Claude 根据用户输入自动选择并读取相应 SKILL.md 执行任务。

        messages    完整对话历史（含所有 user / assistant 轮次）。
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

        # 构建 prompt（按用户身份合并 system + 私有技能）
        skills_index = self._build_skills_index(user_id=user_id)
        conversation_block = self._format_messages(messages)

        context_section = ""
        if context and context.strip():
            truncated = context.strip()[:4000]
            context_section = (
                f"\n\n---\n\n"
                f"## 上一步执行结果（供参考）\n\n{truncated}\n\n"
            )

        skills_root_abs = Path(self.skills_dir).resolve()

        workspace_section = (
            f"**当前会话工作区（你的 cwd）**: `{cwd}`\n"
            f"  - 用户上传文件位于: `{cwd / 'uploads'}`\n"
            f"  - 你生成的所有产物请写入: `{cwd / 'outputs'}`\n"
            f"**技能库根目录（绝对路径，仅可读取）**: `{skills_root_abs}`\n"
        )

        prompt = (
            f"{workspace_section}\n"
            f"## 可用技能列表\n\n"
            f"{skills_index}\n\n"
            f"---\n\n"
            f"## 执行说明\n\n"
            f"请根据用户的最新请求，判断需要使用哪个技能（必要时可组合多个技能），"
            f"使用 Read 工具读取对应 SKILL.md 的**绝对路径**（cwd 已切到会话工作区，相对路径无效），"
            f"然后严格按照技能说明完成任务。\n"
            f"- 所有写文件操作请落在 `{cwd / 'outputs'}` 目录下；不要写到工作区之外。\n"
            f"- 用户上传文件已在消息中提供绝对路径，可直接 Read。\n"
            f"- 所有环境变量均已配置（包括 EIDO_USER_TOKEN），无需手动 export。\n\n"
            f"---\n\n"
            f"## 对话历史\n\n{conversation_block}"
            f"{context_section}"
        )

        logger.debug(f"Prompt 长度: {len(prompt)} 字符")

        # 导入 SDK
        try:
            from claude_agent_sdk import query, ClaudeAgentOptions  # type: ignore
        except ImportError:
            logger.error("claude_agent_sdk 未安装")
            yield self._sse({
                "type": "error",
                "message": "claude_agent_sdk 未安装，请运行: pip install claude-code-sdk"
            })
            yield "data: [DONE]\n\n"
            return

        # 执行
        try:
            agent_env: dict[str, str] = {}
            if user_id:
                from app.core.user_token import create_user_token
                agent_env["EIDO_USER_TOKEN"] = create_user_token(user_id)
            if session_id:
                agent_env["EIDO_SESSION_ID"] = session_id

            options = ClaudeAgentOptions(
                allowed_tools=self.AUTO_ALLOWED_TOOLS,
                cwd=str(cwd),
                setting_sources=["project"],
                permission_mode="acceptEdits",
                env=agent_env,
            )

            logger.info(f"  工具集: {self.AUTO_ALLOWED_TOOLS}")
            logger.info(f"  工作目录: {cwd}")

            async for message in query(prompt=prompt, options=options):
                self._log_message(message)
                for event in self._convert_message(message):
                    yield event

            logger.info("◀ execute_stream 完成")
            yield self._sse({"type": "workflow_complete", "data": {"references": []}})

        except Exception as e:
            logger.error(f"技能自动执行失败: {e}", exc_info=True)
            yield self._sse({"type": "error", "message": f"执行失败: {str(e)}"})

        yield "data: [DONE]\n\n"

    # ------------------------------------------------------------------ #
    #  消息转换                                                             #
    # ------------------------------------------------------------------ #

    def _log_message(self, message: object) -> None:
        """将 SDK 消息写入日志，便于后端实时追踪执行过程"""
        try:
            from claude_agent_sdk.types import (  # type: ignore
                AssistantMessage, UserMessage, SystemMessage, ResultMessage,
                TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock,
            )
        except ImportError:
            return

        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    preview = block.text[:120].replace("\n", " ")
                    logger.info(f"  [Assistant/Text] {preview}{'…' if len(block.text) > 120 else ''}")
                elif isinstance(block, ThinkingBlock):
                    preview = block.thinking[:120].replace("\n", " ")
                    logger.debug(f"  [Assistant/Thinking] {preview}…")
                elif isinstance(block, ToolUseBlock):
                    logger.info(f"  [Tool/Call] {block.name} | 参数: {str(block.input)[:120]}")

        elif isinstance(message, UserMessage):
            if isinstance(message.content, list):
                for block in message.content:
                    if isinstance(block, ToolResultBlock):
                        raw = block.content
                        content_str = raw if isinstance(raw, str) else str(raw or "")
                        preview = content_str[:120].replace("\n", " ")
                        status = "ERROR" if block.is_error else "OK"
                        logger.info(f"  [Tool/Result:{status}] {preview}{'…' if len(content_str) > 120 else ''}")

        elif isinstance(message, SystemMessage):
            logger.info(f"  [System/{message.subtype}] {str(message.data)[:120]}")

        elif isinstance(message, ResultMessage):
            cost = f"${message.total_cost_usd:.4f}" if message.total_cost_usd else "N/A"
            duration = f"{message.duration_ms / 1000:.1f}s"
            status = "ERROR" if message.is_error else "OK"
            logger.info(
                f"  [Result/{status}] 用时={duration} | 费用={cost} | "
                f"轮次={message.num_turns} | session={message.session_id}"
            )

    def _convert_message(self, message: object) -> List[str]:
        """将 claude_agent_sdk 消息转换为前端 SSE 事件列表。

        SDK 返回强类型 dataclass，必须用 isinstance 判断，不能依赖 type 属性。
        消息类型：AssistantMessage / UserMessage / SystemMessage / ResultMessage / StreamEvent
        """
        try:
            from claude_agent_sdk.types import (  # type: ignore
                AssistantMessage, UserMessage, SystemMessage, ResultMessage,
                TextBlock, ThinkingBlock, ToolUseBlock, ToolResultBlock,
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
