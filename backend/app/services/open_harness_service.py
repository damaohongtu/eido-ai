"""
OpenHarness 执行服务：基于 OpenHarness (openharness-ai) 原生 QueryEngine 的 AI Agent 后端。

与 ClaudeSkillService 平级，保持相同的 execute_stream() 接口和 SSE 协议，
内部使用 OpenHarness 原生能力（默认工具集、QueryEngine 对话管理、Skill 工具）。
"""
import asyncio
import json
import logging
import os
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

from app.services.conversation_context import format_recent_conversation
from app.services.project_context import ProjectContext, format_project_context

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SEC = 12.0
_HEARTBEAT_FRAME = ": ping\n\n"

SYSTEM_PROMPT = (
    "You are an AI coding assistant. Use the available tools to help the user "
    "with their software engineering tasks. Think carefully before acting, "
    "and always verify your work.\n\n"
    "You have access to a full set of development tools (bash, file read/write/edit, "
    "glob, grep, web fetch, web search, skills, tasks, agents, and more). "
    "Use them freely to accomplish the user's goals.\n\n"
    "IMPORTANT:\n"
    "- You are working in the session workspace. Uploaded files are in `uploads/`.\n"
    "- Write all generated output to `outputs/` (created automatically).\n"
    "- Use the `skill` tool to discover available skills when relevant.\n"
    "- The skills directory is configured, you can read any SKILL.md by its filename.\n"
    "\n"
    "FILE WRITING STRATEGY:\n"
    "- Use `write_file` for small files (markdown, configs, short scripts).\n"
    "- For LARGE files (HTML reports, long documents, files expected to exceed ~3000 tokens),\n"
    "  write in chunks using Bash heredoc to avoid truncation:\n"
    "  1. First chunk:  cat > outputs/file.html << 'ENDOFFILE'\n"
    "     ...content...\n"
    "     ENDOFFILE\n"
    "  2. Append chunks:  cat >> outputs/file.html << 'ENDOFFILE'\n"
    "     ...more content...\n"
    "     ENDOFFILE\n"
    "  - Use an UNIQUE terminator (like ENDOFFILE or REPORTEND) that does NOT\n"
    "    appear in the file content itself.\n"
    "  - Each chunk should fit comfortably in a single response.\n"
    "  - Always use single-quoted terminator ('ENDOFFILE') to prevent shell expansion.\n"
    "  - If you notice the output is getting very long, proactively switch to this method."
)


class OpenHarnessService:
    """基于 OpenHarness QueryEngine 的执行服务。

    - cwd 按 session 隔离
    - QueryEngine 按 session 缓存，多轮对话自动续接
    - 使用 OpenHarness 默认工具集 + 宽松 write_file
    """

    def __init__(self, skills_dir: Path, workspace_root: Path):
        self.skills_dir = skills_dir
        self.workspace_root = workspace_root
        self._engines: Dict[tuple[str, Optional[str], Optional[int]], object] = {}
        self._ensure_oh()

    # ------------------------------------------------------------------ #
    #  主入口：保持与 ClaudeSkillService 相同的接口                             #
    # ------------------------------------------------------------------ #

    async def execute_stream(
        self, messages: list, context: Optional[str] = None,
        *, user_id: Optional[str] = None, session_id: Optional[str] = None,
        project_context: Optional[ProjectContext] = None,
    ) -> AsyncGenerator[str, None]:
        logger.info(
            f"▶ OH execute_stream | msgs={len(messages)}"
            + (f" | session={session_id}" if session_id else "")
            + (f" | ctx={len(context)}B" if context else "")
        )

        yield _sse({"type": "thinking", "content": "正在分析请求，自动规划执行..."})
        yield _sse({"type": "workflow_start", "skill_name": "auto"})

        cwd = self.workspace_root
        if session_id:
            from app.services.session_workspace import get_session_workspace_manager
            try:
                cwd = get_session_workspace_manager().session_root(session_id)
            except ValueError as e:
                yield _sse({"type": "error", "message": f"非法 session_id: {e}"})
                yield "data: [DONE]\n\n"
                return

        text = _latest_user_text(messages)
        if not text:
            yield _sse({"type": "error", "message": "未找到用户输入"})
            yield "data: [DONE]\n\n"
            return

        engine_key = (
            session_id or "_",
            project_context.id if project_context else None,
            project_context.context_revision if project_context else None,
        )
        prompt_sections: list[str] = []
        project_text = format_project_context(project_context)
        if project_text:
            prompt_sections.append(project_text)
        if engine_key not in self._engines:
            recent_history = format_recent_conversation(messages)
            if recent_history:
                prompt_sections.append(recent_history)
        prompt_sections.append(f"## 用户最新请求\n\n{text}")
        text = "\n\n---\n\n".join(prompt_sections)

        # 管道上下文附加到用户消息
        if context and context.strip():
            text = f"{text}\n\n---\n## 上一步执行结果（供参考）\n\n{context.strip()[:4000]}"

        engine = self._get_engine(engine_key, cwd, user_id)

        # 流式执行 + 心跳
        async def stream_events():
            try:
                async for event in engine.submit_message(text):  # type: ignore[union-attr]
                    for sse in _convert_event(event):
                        yield sse
            except Exception as e:
                logger.error(f"OH 执行失败: {e}", exc_info=True)
                yield _sse({"type": "error", "message": f"执行失败: {e}"})

        queue: asyncio.Queue = asyncio.Queue()
        _DONE = object()

        async def producer():
            try:
                async for ev in stream_events():
                    await queue.put(ev)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"OH stream error: {e}", exc_info=True)
                await queue.put(_sse({"type": "error", "message": f"执行失败: {e}"}))
            finally:
                await queue.put(_DONE)

        async def heartbeat():
            try:
                while True:
                    await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
                    await queue.put(_HEARTBEAT_FRAME)
            except asyncio.CancelledError:
                pass

        pt = asyncio.create_task(producer())
        ht = asyncio.create_task(heartbeat())
        had_error = False
        try:
            while True:
                ev = await queue.get()
                if ev is _DONE:
                    break
                if isinstance(ev, str) and (
                    '"type":"error"' in ev or '"type": "error"' in ev
                ):
                    had_error = True
                yield ev
            if not had_error:
                yield _sse({"type": "workflow_complete", "data": {"references": []}})
            logger.info("◀ OH execute_stream 完成")
        finally:
            ht.cancel()
            if not pt.done():
                pt.cancel()
            for t in (ht, pt):
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass

        yield "data: [DONE]\n\n"

    # ------------------------------------------------------------------ #
    #  Engine                                                              #
    # ------------------------------------------------------------------ #

    def _get_engine(
        self,
        engine_key: tuple[str, Optional[str], Optional[int]],
        cwd: Path,
        user_id: Optional[str],
    ):
        if engine_key in self._engines:
            return self._engines[engine_key]

        engine = self._build_engine(str(cwd), user_id)
        self._engines[engine_key] = engine
        return engine

    def _build_engine(self, cwd: str, user_id: Optional[str]):
        from openharness.config.settings import PermissionSettings  # type: ignore
        from openharness.engine import QueryEngine  # type: ignore
        from openharness.permissions import PermissionChecker  # type: ignore
        from openharness.permissions.modes import PermissionMode  # type: ignore
        from openharness.tools import create_default_tool_registry  # type: ignore

        api_client = _create_api_client()
        tool_registry = create_default_tool_registry()

        perm = PermissionChecker(PermissionSettings(
            mode=PermissionMode.FULL_AUTO,
        ))

        # 技能目录：system + 当前用户私有
        extra_skill_dirs = [str(self.skills_dir / "system")]
        if user_id:
            from app.gateway.sandbox_manager import _safe_user_id
            user_skill_dir = self.skills_dir / "users" / _safe_user_id(user_id)
            if user_skill_dir.exists():
                extra_skill_dirs.append(str(user_skill_dir))

        sys_prompt = (
            f"{SYSTEM_PROMPT}\n\n"
            f"当前工作区: {cwd}\n"
            f"产出目录: {cwd}/outputs\n"
            f"技能目录: {self.skills_dir}\n\n"
            f"你可以使用 `skill` 工具发现和读取可用技能。"
        )

        return QueryEngine(
            api_client=api_client,
            tool_registry=tool_registry,
            permission_checker=perm,
            cwd=cwd,
            model=_resolve_model(),
            system_prompt=sys_prompt,
            max_turns=200,
            max_tokens=16384,
            tool_metadata={"extra_skill_dirs": extra_skill_dirs},
        )

    # ------------------------------------------------------------------ #
    #  工具方法                                                             #
    # ------------------------------------------------------------------ #

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

    def reset_session(self, session_id: str) -> None:
        """Drop cached native context after a session changes Project."""
        keys = [key for key in self._engines if key[0] == session_id]
        for key in keys:
            engine = self._engines.pop(key, None)
            if engine is not None and hasattr(engine, "clear"):
                engine.clear()


# ------------------------------------------------------------------ #
#  模块级工具函数                                                        #
# ------------------------------------------------------------------ #

def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _resolve_model() -> str:
    return os.environ.get("ANTHROPIC_MODEL", "").strip() or "claude-sonnet-4-6"


def _latest_user_text(messages: list) -> str:
    def _role(m):
        return getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else "") or ""

    def _content(m):
        c = getattr(m, "content", None) if not isinstance(m, dict) else m.get("content")
        return (c or "").strip()

    for msg in reversed(messages or []):
        if _role(msg) == "user":
            return _content(msg)
    return ""


def _create_api_client():
    from openharness.api import AnthropicApiClient  # type: ignore

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or None
    auth_token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "").strip() or None
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or None

    if not api_key and not auth_token:
        raise RuntimeError(
            "OpenHarness 需要 ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN 环境变量"
        )

    kwargs: dict = {}
    if api_key:
        kwargs["api_key"] = api_key
    if auth_token:
        kwargs["auth_token"] = auth_token
    if base_url:
        kwargs["base_url"] = base_url

    logger.info(f"AnthropicApiClient | base_url={base_url or '默认'}")
    return AnthropicApiClient(**kwargs)


def _convert_event(event: object) -> List[str]:
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

    out: List[str] = []

    if isinstance(event, AssistantTextDelta):
        if event.text:
            out.append(_sse({"type": "content", "content": event.text}))

    elif isinstance(event, ToolExecutionStarted):
        hint = f"执行工具: {event.tool_name}"
        try:
            hint += f" | 参数: {str(event.tool_input)[:120]}"
        except Exception:
            pass
        out.append(_sse({"type": "thinking", "content": hint}))

    elif isinstance(event, ToolExecutionCompleted):
        preview = (event.output or "")[:200].strip()
        status = "✗ 工具出错" if event.is_error else "✓ 工具完成"
        out.append(_sse({"type": "thinking", "content": f"{status}: {preview}" if preview else status}))

    elif isinstance(event, ErrorEvent):
        out.append(_sse({"type": "error", "message": event.message}))

    elif isinstance(event, StatusEvent):
        if event.message:
            out.append(_sse({"type": "thinking", "content": event.message}))

    elif isinstance(event, AssistantTurnComplete):
        u = event.usage
        out.append(_sse({"type": "thinking", "content": f"执行完成 | 输入: {u.input_tokens} tokens | 输出: {u.output_tokens} tokens"}))

    return out


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
