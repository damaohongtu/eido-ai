"""
OpenHarness 技能服务：基于 OpenHarness (openharness-ai) 的 AI Agent 执行后端。

独立于 ClaudeSkillService，通过 AGENT_HARNESS=open_harness 配置启用。
提供与 ClaudeSkillService 相同的 execute_stream() 接口，chat 端点无需改动。
"""
import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_TOOLS = ["Bash", "Glob", "Read", "WebFetch"]

HEARTBEAT_INTERVAL_SEC = 12.0
_HEARTBEAT_FRAME = ": ping\n\n"

DEFAULT_SYSTEM_PROMPT = (
    "You are an AI coding assistant. Use the available tools to help the user "
    "with their software engineering tasks. Think carefully before acting, "
    "and always verify your work."
)
DEFAULT_MAX_TURNS = 50

_TOOL_MODULES: Dict[str, tuple[str, str]] = {
    "Bash":      ("openharness.tools.bash_tool",       "BashTool"),
    "Read":      ("openharness.tools.file_read_tool",  "FileReadTool"),
    "Write":     ("openharness.tools.file_write_tool", "FileWriteTool"),
    "Edit":      ("openharness.tools.file_edit_tool",  "FileEditTool"),
    "Glob":      ("openharness.tools.glob_tool",       "GlobTool"),
    "Grep":      ("openharness.tools.grep_tool",       "GrepTool"),
    "WebFetch":  ("openharness.tools.web_fetch_tool",  "WebFetchTool"),
    "WebSearch": ("openharness.tools.web_search_tool", "WebSearchTool"),
}


class OpenHarnessService:
    """基于 OpenHarness QueryEngine 的技能执行服务。

    通过 AGENT_HARNESS=open_harness 配置启用，与 ClaudeSkillService 平级。
    cwd 切到 session 工作区，支持 resume（跨轮次续接）。
    """

    AUTO_ALLOWED_TOOLS = ["Bash", "Glob", "Read", "Write", "Edit", "WebFetch"]

    def __init__(self, skills_dir: Path, workspace_root: Path):
        self.skills_dir = skills_dir
        self.workspace_root = workspace_root
        self._engines: Dict[str, object] = {}  # session_id → QueryEngine

    # ------------------------------------------------------------------ #
    #  技能扫描（复用 ClaudeSkillService 逻辑）                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _extract_latest_user_text(messages: list) -> str:
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

    def scan_skills(self, *, user_id: Optional[str] = None) -> list:
        """扫描可用技能。"""
        from app.services.claude_skill_service import get_claude_skill_service
        svc = get_claude_skill_service()
        if svc:
            return svc.scan_skills(user_id=user_id)
        return []

    def _build_skills_index(self, *, user_id: Optional[str] = None) -> str:
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

    # ------------------------------------------------------------------ #
    #  主入口                                                              #
    # ------------------------------------------------------------------ #

    async def execute_stream(
        self, messages: list, context: Optional[str] = None,
        *, user_id: Optional[str] = None, session_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """通过 OpenHarness QueryEngine 自动规划执行，以 SSE 格式流式返回。"""
        logger.info(
            f"▶ OpenHarness execute_stream | 消息数: {len(messages)}"
            + (f" | session={session_id}" if session_id else "")
            + (f" | 含上下文 {len(context)} 字符" if context else "")
        )

        yield self._sse({"type": "thinking", "content": "正在分析请求，自动规划执行..."})
        yield self._sse({"type": "workflow_start", "skill_name": "auto"})

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

        self._ensure_oh()

        latest_user_text = self._extract_latest_user_text(messages)
        if not latest_user_text:
            yield self._sse({"type": "error", "message": "未找到用户输入"})
            yield "data: [DONE]\n\n"
            return

        claude_sid = self._load_claude_sid(user_id, session_id)

        async def _run_once(resume_sid: Optional[str]) -> AsyncGenerator[str, None]:
            prompt = self._build_prompt(
                cwd=cwd,
                latest_user_text=latest_user_text,
                context=context,
                user_id=user_id,
                resume=bool(resume_sid),
            )
            engine = self._get_or_create_engine(
                cwd=str(cwd),
                resume_session_id=resume_sid,
            )
            logger.info(
                f"  resume={resume_sid or '(none)'} | 工具集={self.AUTO_ALLOWED_TOOLS} "
                f"| prompt={len(prompt)}B | cwd={cwd}"
            )

            async for event in engine.submit_message(prompt):  # type: ignore[union-attr]
                for sse in self._convert_event(event):
                    yield sse

        # ---- 生产者 + 心跳 ----
        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()
        had_error = {"v": False}

        async def producer() -> None:
            tried_resume = bool(claude_sid)
            try:
                if tried_resume:
                    try:
                        async for ev in _run_once(claude_sid):
                            await queue.put(ev)
                        return
                    except Exception as e:
                        logger.warning(
                            f"resume({claude_sid}) 失败，清 sid 并回退到首轮: {e}"
                        )
                        if session_id:
                            self._save_claude_sid(user_id, session_id, None)
                        await queue.put(
                            self._sse({"type": "thinking", "content": "原会话已失效，重建中..."})
                        )
                async for ev in _run_once(None):
                    await queue.put(ev)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"OpenHarness 执行失败: {e}", exc_info=True)
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
            logger.info("◀ OpenHarness execute_stream 完成")
        finally:
            hb_task.cancel()
            if not prod_task.done():
                prod_task.cancel()
            for t in (hb_task, prod_task):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

        yield "data: [DONE]\n\n"

    # ------------------------------------------------------------------ #
    #  Engine 生命周期                                                      #
    # ------------------------------------------------------------------ #

    def _get_or_create_engine(
        self,
        *,
        cwd: str,
        resume_session_id: Optional[str] = None,
    ):
        if resume_session_id and resume_session_id in self._engines:
            logger.info(f"复用 QueryEngine: session={resume_session_id}")
            return self._engines[resume_session_id]

        engine = self._build_engine(cwd=cwd)
        sid = resume_session_id or self._new_session_id()
        self._engines[sid] = engine
        logger.info(f"创建 QueryEngine: session={sid}")
        return engine

    def _build_engine(self, *, cwd: str):
        from openharness.engine import QueryEngine  # type: ignore

        api_client = self._create_api_client()
        tool_registry = self._create_tool_registry()
        permission_checker = self._create_permission_checker()

        return QueryEngine(
            api_client=api_client,
            tool_registry=tool_registry,
            permission_checker=permission_checker,
            cwd=cwd,
            model=self._resolve_model(),
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            max_turns=DEFAULT_MAX_TURNS,
            settings=None,
        )

    # ------------------------------------------------------------------ #
    #  API Client                                                          #
    # ------------------------------------------------------------------ #

    def _create_api_client(self):
        from openharness.api import AnthropicApiClient  # type: ignore

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or None
        auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip() or None
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or None

        return AnthropicApiClient(
            api_key=api_key,
            auth_token=auth_token,
            base_url=base_url,
        )

    # ------------------------------------------------------------------ #
    #  Tool Registry                                                       #
    # ------------------------------------------------------------------ #

    def _create_tool_registry(self):
        from openharness.tools.base import ToolRegistry  # type: ignore

        registry = ToolRegistry()
        for tool_name in self.AUTO_ALLOWED_TOOLS:
            info = _TOOL_MODULES.get(tool_name)
            if info is None:
                logger.warning(f"OpenHarness 不支持工具: {tool_name}，已跳过")
                continue
            module_path, class_name = info
            try:
                import importlib
                mod = importlib.import_module(module_path)
                tool_cls = getattr(mod, class_name)
                registry.register(tool_cls())
            except Exception as e:
                logger.warning(f"注册工具失败 {tool_name}: {e}")
        return registry

    # ------------------------------------------------------------------ #
    #  Permission                                                           #
    # ------------------------------------------------------------------ #

    def _create_permission_checker(self):
        from openharness.config.settings import PermissionSettings  # type: ignore
        from openharness.permissions import PermissionChecker  # type: ignore
        from openharness.permissions.modes import PermissionMode  # type: ignore

        perm_settings = PermissionSettings(
            mode=PermissionMode.FULL_AUTO,
            allowed_tools=list(self.AUTO_ALLOWED_TOOLS),
        )
        return PermissionChecker(perm_settings)

    # ------------------------------------------------------------------ #
    #  Prompt 构建                                                          #
    # ------------------------------------------------------------------ #

    def _build_prompt(
        self,
        *,
        cwd: Path,
        latest_user_text: str,
        context: Optional[str],
        user_id: Optional[str],
        resume: bool,
    ) -> str:
        context_section = ""
        if context and context.strip():
            truncated = context.strip()[:4000]
            context_section = (
                f"\n\n---\n\n## 上一步执行结果（供参考）\n\n{truncated}\n"
            )

        if resume:
            return (
                f"## 用户最新请求\n\n{latest_user_text}"
                f"{context_section}"
            )

        skills_index = self._build_skills_index(user_id=user_id)
        skills_root_abs = Path(self.skills_dir).resolve()
        workspace_section = (
            f"**当前会话工作区（你的 cwd）**: `{cwd}`\n"
            f"  - 用户上传文件位于: `{cwd / 'uploads'}`\n"
            f"  - 你生成的所有产物请写入: `{cwd / 'outputs'}`\n"
            f"**技能库根目录（绝对路径，仅可读取）**: `{skills_root_abs}`\n"
        )
        return (
            f"{workspace_section}\n"
            f"## 可用技能列表\n\n{skills_index}\n\n"
            f"---\n\n"
            f"## 执行说明\n\n"
            f"请根据用户的最新请求，判断需要使用哪个技能（必要时可组合多个技能），"
            f"使用 Read 工具读取对应 SKILL.md 的**绝对路径**（cwd 已切到会话工作区，相对路径无效），"
            f"然后严格按照技能说明完成任务。\n"
            f"- 所有写文件操作请落在 `{cwd / 'outputs'}` 目录下；不要写到工作区之外。\n"
            f"- 用户上传文件已在消息中提供绝对路径，可直接 Read。\n"
            f"- 所有环境变量均已配置（包括 EIDO_USER_TOKEN），无需手动 export。\n\n"
            f"---\n\n"
            f"## 用户最新请求\n\n{latest_user_text}"
            f"{context_section}"
        )

    # ------------------------------------------------------------------ #
    #  Session 管理                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_agent_env(user_id: Optional[str], session_id: Optional[str]) -> dict:
        env: dict[str, str] = {}
        if user_id:
            from app.core.user_token import create_user_token
            env["EIDO_USER_TOKEN"] = create_user_token(user_id)
        if session_id:
            env["EIDO_SESSION_ID"] = session_id
        return env

    @staticmethod
    def _load_claude_sid(user_id: Optional[str], session_id: Optional[str]) -> Optional[str]:
        if not (user_id and session_id):
            return None
        try:
            from app.services.chat_session_store import get_chat_session_store
            return get_chat_session_store().get_claude_session_id(user_id, session_id)
        except Exception as e:
            logger.warning(f"读取 session_id 失败: {e}")
            return None

    @staticmethod
    def _save_claude_sid(
        user_id: Optional[str], session_id: Optional[str], sid: Optional[str]
    ) -> None:
        if not (user_id and session_id):
            return
        from app.services.chat_session_store import get_chat_session_store
        get_chat_session_store().set_claude_session_id(user_id, session_id, sid)

    # ------------------------------------------------------------------ #
    #  事件转换：OpenHarness StreamEvent → SSE                              #
    # ------------------------------------------------------------------ #

    def _convert_event(self, event: object) -> List[str]:
        try:
            from openharness.engine.stream_events import (  # type: ignore
                AssistantTextDelta,
                AssistantTurnComplete,
                ErrorEvent,
                StatusEvent,
                ToolExecutionCompleted,
                ToolExecutionStarted,
            )
        except ImportError:
            return []

        events: List[str] = []

        if isinstance(event, AssistantTextDelta):
            if event.text:
                events.append(self._sse({"type": "content", "content": event.text}))

        elif isinstance(event, ToolExecutionStarted):
            hint = f"执行工具: {event.tool_name}"
            try:
                arg_preview = str(event.tool_input)[:120]
                hint = f"{hint} | 参数: {arg_preview}"
            except Exception:
                pass
            events.append(self._sse({"type": "thinking", "content": hint}))

        elif isinstance(event, ToolExecutionCompleted):
            preview = (event.output or "")[:200].strip()
            status = "✗ 工具出错" if event.is_error else "✓ 工具完成"
            hint = f"{status}: {preview}" if preview else status
            events.append(self._sse({"type": "thinking", "content": hint}))

        elif isinstance(event, ErrorEvent):
            events.append(self._sse({
                "type": "error",
                "message": event.message,
            }))

        elif isinstance(event, StatusEvent):
            if event.message:
                events.append(self._sse({
                    "type": "thinking",
                    "content": event.message,
                }))

        elif isinstance(event, AssistantTurnComplete):
            usage = event.usage
            cost_info = (
                f"执行完成 | 输入: {usage.input_tokens} tokens "
                f"| 输出: {usage.output_tokens} tokens"
            )
            events.append(self._sse({
                "type": "thinking",
                "content": cost_info,
            }))

        return events

    # ------------------------------------------------------------------ #
    #  工具方法                                                             #
    # ------------------------------------------------------------------ #

    def _sse(self, data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _resolve_model(self) -> str:
        model = os.environ.get("ANTHROPIC_MODEL", "").strip()
        return model or "claude-sonnet-4-6"

    def _new_session_id(self) -> str:
        return f"oh-{uuid.uuid4().hex[:12]}"

    # ------------------------------------------------------------------ #
    #  SDK 可用性检查                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_available() -> bool:
        try:
            import openharness  # type: ignore # noqa: F401
            return True
        except ImportError:
            return False

    @staticmethod
    def _ensure_oh() -> None:
        try:
            import openharness  # type: ignore # noqa: F401
        except ImportError as e:
            raise ImportError(
                "openharness-ai 未安装，请运行: pip install openharness-ai"
            ) from e

    def close(self) -> None:
        for engine in self._engines.values():
            if hasattr(engine, "clear"):
                engine.clear()
        self._engines.clear()


# ------------------------------------------------------------------ #
#  全局单例                                                             #
# ------------------------------------------------------------------ #

_instance: Optional[OpenHarnessService] = None


def get_open_harness_service() -> Optional[OpenHarnessService]:
    return _instance


def init_open_harness_service(
    skills_dir: Path, workspace_root: Path
) -> OpenHarnessService:
    global _instance
    _instance = OpenHarnessService(skills_dir, workspace_root)
    logger.info(f"OpenHarnessService 初始化完成 - 技能目录: {skills_dir}")
    return _instance
