"""Claude Code runtime orchestration for one Eido user container."""

import asyncio
import hashlib
import json
import logging
import time
from contextlib import aclosing
from dataclasses import replace
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from app.services.chat.events import ChatEvent, StreamSignal
from app.services.claude.context import context_instructions, prepare_recovery_context
from app.services.claude.execution_profile import QA_SYSTEM_PROMPT, get_execution_profile
from app.services.claude.prompt import (
    auth_error,
    auth_summary,
    build_agent_env,
    build_prompt,
    build_qa_prompt,
)
from app.services.claude.session_pool import ClaudeSessionPool
from app.services.claude.turn import RateLimitPause, ResumeUnavailable, stream_turn
from app.services.projects.context import ProjectContext
from app.services.skills.catalog import SkillCatalog

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SEC = 12.0


class ClaudeRuntime:
    """Coordinate prompts, native sessions, skills, MCP and chat events."""

    def __init__(self, skills_dir: Path, workspace_root: Path):
        self.workspace_root = workspace_root
        self.sessions = ClaudeSessionPool()
        self.catalog = SkillCatalog(skills_dir, self.sessions.reset_user)

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
        "NotebookEdit",
        "Agent",
        "TodoWrite",
        "TaskCreate",
        "TaskUpdate",
        "TaskGet",
        "TaskList",
        "TaskOutput",
        "TaskStop",
    ]

    @staticmethod
    def _extract_latest_user_text(messages: list) -> str:
        """从消息列表尾部找出最后一条 user 消息文本。

        切换到原生 resume 后，对话历史由 Claude Code 自己的 jsonl 维护，
        后端不再重复重建历史，prompt 只携带"本轮最新一条 user 输入"。
        """

        for msg in reversed(messages or []):
            if isinstance(msg, dict):
                role, content = msg.get("role"), msg.get("content")
            else:
                role, content = getattr(msg, "role", None), getattr(msg, "content", None)
            if role == "user":
                return (content or "").strip()
        return ""

    def reset_session(self, session_id: str) -> None:
        """驱逐指定 Eido session 的长连接；供项目切换/删除时调用。"""
        self.catalog.forget_session(session_id)
        self.sessions.reset_session(session_id)

    def reset_user(self, user_id: str) -> None:
        """Evict every warm Claude client after user-scoped MCP config changes."""
        self.sessions.reset_user(user_id)

    def can_steer_session(self, user_id: Optional[str], session_id: str) -> bool:
        return self.sessions.can_steer(user_id, session_id)

    async def steer_session(
        self,
        user_id: Optional[str],
        session_id: str,
        content: str,
    ) -> bool:
        """Inject additional user input into the active streaming Claude turn.

        ``ClaudeSDKClient`` keeps stdin open in streaming mode. Sending another
        user message while ``receive_response()`` is active is the Claude Code
        equivalent of Codex Steer: the model receives the new direction without
        first cancelling the running turn.
        """
        steered = await self.sessions.steer(user_id, session_id, content)
        if steered:
            logger.info("Claude session 已注入 steer: session=%s", session_id)
        return steered

    async def interrupt_session(self, user_id: Optional[str], session_id: str) -> bool:
        """Interrupt an active turn. Reserved for the explicit stop action."""
        interrupted = await self.sessions.interrupt(user_id, session_id)
        if interrupted:
            logger.info("Claude session 已中断: session=%s", session_id)
        return interrupted

    async def shutdown(self) -> None:
        """应用关闭时回收所有 Claude Code 子进程。"""
        await self.sessions.shutdown()

    async def stream_events(
        self,
        messages: list,
        context: Optional[str] = None,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        project_context: Optional[ProjectContext] = None,
        project_id: Optional[str] = None,
        model: Optional[str] = None,
        runtime_mode: str = "agent",
    ) -> AsyncGenerator[ChatEvent, None]:
        """通过 claude_agent_sdk 自动规划执行，流式返回对话事件。

        架构要点：
        - 使用 Claude Code 原生 `resume` 续接：每个 eido 会话首轮跑出 claude_session_id
          后落盘到 chat_sessions.claude_session_id；后续轮次只需 resume，
          prompt 仅携带本轮最新一条 user 消息（历史/记忆由 Claude Code 自己的 jsonl 管）。
        - 心跳：长任务期间每 ~12s 推一个注释帧，防止前端 fetch 在静默期断连。
        - resume 失败时（claude jsonl 缺失/损坏）自动清掉旧 sid，回退到首轮模式重跑。

        messages    完整对话历史（仅本轮最新一条 user 真正进入 prompt）。
        context     多技能流水线中上一步的输出，附加在 prompt 末尾。
        user_id     当前用户 ID，用于生成 agent 子进程的身份 token。
        session_id  会话 ID。指定后 agent cwd 切到该会话工作区（强隔离）；
                    未指定则回退到全局 workspace_root（兼容历史路径）。
        """
        profile = get_execution_profile(runtime_mode)
        project_id = project_context.id if project_context else project_id
        project_context = project_context if profile.project_context_enabled else None
        logger.info(
            f"▶ stream_events 开始 | mode={profile.mode} | 消息数: {len(messages)}"
            + (f" | session={session_id}" if session_id else "")
            + (f" | 含上下文 {len(context)} 字符" if context else "")
        )

        latest_user_text = self._extract_latest_user_text(messages)
        if not latest_user_text:
            yield {"type": "error", "message": "未找到用户输入"}
            yield StreamSignal.DONE
            return

        yield {
            "type": "thinking",
            "content": ("正在回答..." if profile.mode == "qa" else "正在分析请求，自动规划执行..."),
        }
        if profile.mode == "agent":
            yield {"type": "workflow_start", "skill_name": "auto"}

        # 解析 cwd（按 session 隔离时使用 session 工作区）
        if session_id:
            from app.services.chat.session_workspace import get_session_workspace_manager

            try:
                cwd = get_session_workspace_manager().session_root(session_id)
            except ValueError as e:
                yield {"type": "error", "message": f"非法 session_id: {e}"}
                yield StreamSignal.DONE
                return
        else:
            cwd = self.workspace_root

        native_skills = profile.skills_enabled and bool(session_id)
        skill_revision: tuple[Any, ...] = ()
        skill_count = 0
        if native_skills:
            try:
                skill_revision, skill_count = self.catalog.materialize_native_view(
                    cwd, user_id=user_id
                )
            except Exception:
                logger.exception("原生技能映射失败，回退到兼容技能索引")
                native_skills = False

        # 导入 SDK
        try:
            from claude_agent_sdk import ClaudeAgentOptions, HookMatcher
        except ImportError:
            logger.error("claude_agent_sdk 未安装")
            yield {
                "type": "error",
                "message": "claude_agent_sdk 未安装，请运行: pip install claude-agent-sdk",
            }
            yield StreamSignal.DONE
            return

        from app.core.config import settings
        from app.services.claude.models import load_model_catalog

        model_spec = load_model_catalog().find(model)
        provider_model = model_spec.model
        provider_env = model_spec.agent_env(
            settings.claude_agent_env,
            relay=settings.EIDO_TRUST_GATEWAY,
        )
        claude_sid = self._load_claude_sid(
            user_id, session_id, project_id=project_id, project_context=project_context
        )
        agent_env = build_agent_env(
            user_id,
            session_id,
            project_id,
            provider_env=provider_env,
        )
        if profile.mcp_enabled:
            from app.services.mcp.config_store import get_mcp_config_store

            mcp_servers, mcp_revision = get_mcp_config_store().sdk_servers(user_id)
        else:
            mcp_servers, mcp_revision = {}, 0
        profile_dir = Path(agent_env["CLAUDE_CONFIG_DIR"])
        memory_scope = f"project-{project_context.id}" if project_context else "personal"
        memory_dir = profile_dir / "eido-memory" / memory_scope
        profile_dir.mkdir(parents=True, exist_ok=True)
        memory_settings: dict[str, bool | str] = {"autoMemoryEnabled": profile.memory_enabled}
        if profile.memory_enabled:
            memory_dir.mkdir(parents=True, exist_ok=True)
            memory_settings["autoMemoryDirectory"] = str(memory_dir)
        auth_problem = auth_error(agent_env)
        if auth_problem:
            logger.error("Claude Agent SDK 认证配置缺失: %s", auth_problem)
            yield {"type": "error", "message": auth_problem}
            yield StreamSignal.DONE
            return
        auth_mode, provider = auth_summary(agent_env)
        logger.info("  [ClaudeAuth] mode=%s provider=%s", auth_mode, provider)
        project_signature = (
            (
                project_id,
                project_context.context_revision,
            )
            if project_context
            else (project_id, None)
        )

        def _secret_digest(name: str) -> str:
            value = provider_env.get(name, "")
            return hashlib.sha256(value.encode()).hexdigest() if value else ""

        client_signature = (
            profile.mode,
            model_spec.id,
            provider_model,
            provider_env.get("ANTHROPIC_BASE_URL", ""),
            _secret_digest("ANTHROPIC_API_KEY"),
            _secret_digest("ANTHROPIC_AUTH_TOKEN"),
            provider_env.get("ANTHROPIC_SMALL_FAST_MODEL", ""),
            settings.CLAUDE_EFFORT,
            str(cwd.resolve()),
            project_signature,
            skill_revision,
            mcp_revision,
        )

        available_tools = list(self.AUTO_ALLOWED_TOOLS) if profile.tools_enabled else []
        if native_skills:
            available_tools.append("Skill")

        async def before_compact(input_data, tool_use_id, hook_context):
            prepare_recovery_context(cwd, user_id, session_id, [])
            return {}

        options = ClaudeAgentOptions(
            model=provider_model,
            effort=profile.effort(settings.CLAUDE_EFFORT),
            cli_path=settings.CLAUDE_CLI_PATH or None,
            system_prompt=(
                {
                    "type": "preset",
                    "preset": "claude_code",
                    "append": context_instructions(cwd),
                }
                if profile.mode == "agent"
                else QA_SYSTEM_PROMPT
            ),
            hooks=(
                {"PreCompact": [HookMatcher(hooks=[before_compact])]}
                if profile.mode == "agent"
                else {}
            ),
            allowed_tools=[*available_tools, *(f"mcp__{name}__*" for name in mcp_servers)],
            tools=available_tools,
            cwd=str(cwd),
            setting_sources=["project"] if native_skills else [],
            skills="all" if native_skills else None,
            permission_mode=profile.permission_mode,
            include_partial_messages=True,
            max_buffer_size=10 * 1024 * 1024,
            mcp_servers=mcp_servers,
            strict_mcp_config=True,
            max_turns=profile.max_turns,
            settings=json.dumps(memory_settings),
        )

        queue: asyncio.Queue[ChatEvent | None] = asyncio.Queue(maxsize=256)
        had_error = False

        def save_native_session(sid: str | None) -> None:
            self._save_claude_sid(
                user_id, session_id, sid, project_id=project_id, project_context=project_context
            )

        async def run_turn(resume_sid: Optional[str], retrying: bool) -> None:
            nonlocal had_error
            effective_user_text = (
                "额度已恢复。继续尚未完成的原任务，保留用户追加的要求；先检查已完成步骤，不要重复执行有副作用的操作。"
                if retrying and resume_sid
                else latest_user_text
            )
            recovery_context = (
                prepare_recovery_context(cwd, user_id, session_id, messages)
                if not resume_sid
                else ""
            )
            if profile.mode == "qa":
                prompt = build_qa_prompt(
                    cwd=cwd,
                    latest_user_text=effective_user_text,
                    context=context,
                    resume=bool(resume_sid),
                    conversation_history=recovery_context,
                )
            else:
                prompt = build_prompt(
                    cwd=cwd,
                    skills_dir=self.catalog.skills_dir,
                    latest_user_text=effective_user_text,
                    context=context,
                    resume=bool(resume_sid),
                    project_context=project_context,
                    conversation_history=recovery_context,
                    native_skills=native_skills,
                    fallback_skills_index=(
                        "" if native_skills else self.catalog.prompt_index(user_id=user_id)
                    ),
                )
            if latest_user_text.strip().split(maxsplit=1)[0] == "/compact" and not retrying:
                prompt = latest_user_text.strip()
            # Refresh the task token after any quota wait.
            turn_options = replace(
                options,
                resume=resume_sid,
                env=(
                    build_agent_env(user_id, session_id, project_id, provider_env=provider_env)
                    if retrying
                    else agent_env
                ),
            )
            async with aclosing(
                stream_turn(
                    self.sessions,
                    prompt,
                    options=turn_options,
                    signature=client_signature,
                    user_id=user_id,
                    session_id=session_id,
                    save_session=save_native_session,
                    runtime_mode=profile.mode,
                    skill_count=skill_count,
                )
            ) as events:
                async for event in events:
                    had_error |= event["type"] == "error"
                    await queue.put(event)

        async def producer() -> None:
            nonlocal had_error
            retrying = False
            resume_sid = claude_sid
            retry_count = 0
            try:
                while True:
                    try:
                        await run_turn(resume_sid, retrying)
                        break
                    except ResumeUnavailable:
                        if retrying:
                            raise RuntimeError(
                                "限流后原生会话无法恢复，请检查已完成步骤后继续"
                            ) from None
                        save_native_session(None)
                        resume_sid = None
                        await queue.put(
                            {
                                "type": "thinking",
                                "content": "原生会话不可用，正在从完整历史恢复…",
                            }
                        )
                    except RateLimitPause as exc:
                        retry_count += 1
                        delay = (
                            max(1, exc.resets_at - time.time() + 1)
                            if exc.resets_at
                            else min(60, 5 * 2 ** min(retry_count - 1, 4))
                        )
                        await queue.put(
                            {
                                "type": "thinking",
                                "content": (
                                    f"模型额度受限，约 {int(delay)} 秒后自动继续；可随时停止。"
                                ),
                            }
                        )
                        deadline = time.monotonic() + delay
                        while time.monotonic() < deadline:
                            await asyncio.sleep(min(60, deadline - time.monotonic()))
                        resume_sid = self._load_claude_sid(
                            user_id,
                            session_id,
                            project_id=project_id,
                            project_context=project_context,
                        )
                        if not resume_sid:
                            raise RuntimeError(
                                "限流前未保存原生会话，无法安全自动续接，请重试"
                            ) from None
                        retrying = True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Claude Code 执行失败")
                had_error = True
                await queue.put({"type": "error", "message": str(exc)})
            finally:
                if not asyncio.current_task().cancelling():
                    await queue.put(None)

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
                await queue.put(StreamSignal.HEARTBEAT)

        prod_task = asyncio.create_task(producer())
        hb_task = asyncio.create_task(heartbeat())

        try:
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                yield ev
            if not had_error:
                yield {"type": "workflow_complete", "data": {"references": []}}
            logger.info("◀ stream_events 完成")
        finally:
            hb_task.cancel()
            prod_task.cancel()
            await asyncio.gather(hb_task, prod_task, return_exceptions=True)

        yield StreamSignal.DONE

    # ------------------------------------------------------------------ #
    #  prompt / options 辅助                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_claude_sid(
        user_id: Optional[str],
        session_id: Optional[str],
        *,
        project_id: Optional[str],
        project_context: Optional[ProjectContext],
    ) -> Optional[str]:
        if not (user_id and session_id):
            return None
        try:
            from app.services.chat.session_store import get_chat_session_store

            guard: dict[str, object] = {"expected_project_id": project_id}
            if project_context:
                guard["expected_context_revision"] = project_context.context_revision
            return get_chat_session_store().get_claude_session_id(user_id, session_id, **guard)
        except Exception as e:
            logger.warning(f"读取 claude_session_id 失败: {e}")
            return None

    @staticmethod
    def _save_claude_sid(
        user_id: Optional[str],
        session_id: Optional[str],
        claude_sid: Optional[str],
        *,
        project_id: Optional[str],
        project_context: Optional[ProjectContext],
    ) -> None:
        if not (user_id and session_id):
            return
        from app.services.chat.session_store import get_chat_session_store

        guard: dict[str, object] = {"expected_project_id": project_id}
        if project_context:
            guard["expected_context_revision"] = project_context.context_revision
        saved = get_chat_session_store().set_claude_session_id(
            user_id, session_id, claude_sid, **guard
        )
        if not saved:
            logger.info("忽略已过期请求返回的 Claude session ID: session=%s", session_id)


_instance: Optional[ClaudeRuntime] = None


def get_claude_runtime() -> Optional[ClaudeRuntime]:
    """获取全局单例，startup 完成后才非 None。"""
    return _instance


def init_claude_runtime(skills_dir: Path, workspace_root: Path) -> ClaudeRuntime:
    global _instance
    _instance = ClaudeRuntime(skills_dir, workspace_root)
    logger.info(f"ClaudeRuntime 初始化完成 - 技能目录: {skills_dir}")
    return _instance
