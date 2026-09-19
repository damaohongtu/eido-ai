"""Claude Code runtime orchestration for one Eido user container."""

import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from app.services.claude_prompt import (
    AUTH_FAILURE_MESSAGE,
    auth_error,
    auth_summary,
    build_agent_env,
    build_prompt,
    is_not_logged_in_message,
)
from app.services.claude_session_pool import ClaudeSessionEntry, ClaudeSessionPool
from app.services.conversation_context import context_instructions, prepare_recovery_context
from app.services.project_context import ProjectContext
from app.services.skill_catalog import SkillCatalog

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SEC = 12.0
_HEARTBEAT_FRAME = ": ping\n\n"


class _ResumeUnavailable(RuntimeError):
    """原生会话在产生本轮输出前已不可恢复，可安全回退到重建模式。"""

    def __init__(self, cause: Exception):
        super().__init__(str(cause))
        self.cause = cause


class _RateLimitPause(RuntimeError):
    def __init__(self, resets_at=None):
        self.resets_at = resets_at


class _AgentAuthenticationError(RuntimeError):
    """Agent SDK could not use a supported non-interactive credential."""


class ClaudeRuntime(SkillCatalog):
    """Coordinate prompts, native sessions, skills, MCP and SSE events."""

    def __init__(self, skills_dir: Path, workspace_root: Path):
        super().__init__(skills_dir, workspace_root)
        self.sessions = ClaudeSessionPool()

    def _on_catalog_changed(self, user_id: str | None) -> None:
        self.sessions.reset_user(user_id)

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

        def _role(m: object) -> str:
            return getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else "") or ""

        def _content(m: object) -> str:
            c = getattr(m, "content", None) if not isinstance(m, dict) else m.get("content")
            return (c or "").strip()

        for msg in reversed(messages or []):
            if _role(msg) == "user":
                return _content(msg)
        return ""

    def reset_session(self, session_id: str) -> None:
        """驱逐指定 Eido session 的长连接；供项目切换/删除时调用。"""
        for path in list(self._native_skill_views):
            if Path(path).name == session_id:
                self._native_skill_views.pop(path, None)
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

    async def execute_stream(
        self,
        messages: list,
        context: Optional[str] = None,
        *,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        project_context: Optional[ProjectContext] = None,
        model: Optional[str] = None,
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

        latest_user_text = self._extract_latest_user_text(messages)
        if not latest_user_text:
            yield self._sse({"type": "error", "message": "未找到用户输入"})
            yield "data: [DONE]\n\n"
            return

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
                skill_revision, skill_count = self._materialize_native_skills(cwd, user_id=user_id)
            except Exception:
                logger.exception("原生技能映射失败，回退到兼容技能索引")
                native_skills = False

        # 导入 SDK
        try:
            from claude_agent_sdk import (  # type: ignore
                ClaudeAgentOptions,
                ClaudeSDKError,
                HookMatcher,
                query,
            )
        except ImportError:
            logger.error("claude_agent_sdk 未安装")
            yield self._sse(
                {
                    "type": "error",
                    "message": "claude_agent_sdk 未安装，请运行: pip install claude-agent-sdk",
                }
            )
            yield "data: [DONE]\n\n"
            return

        from app.core.config import settings
        from app.services.model_catalog import load_model_catalog

        model_spec = load_model_catalog().find(model)
        provider_model = model_spec.model
        provider_env = model_spec.agent_env(
            settings.claude_agent_env,
            relay=settings.EIDO_TRUST_GATEWAY,
        )
        claude_sid = self._load_claude_sid(user_id, session_id, project_context=project_context)
        agent_env = build_agent_env(
            user_id,
            session_id,
            project_context.id if project_context else None,
            provider_env=provider_env,
        )
        from app.services.mcp_config_store import get_mcp_config_store

        mcp_servers, mcp_revision = get_mcp_config_store().sdk_servers(user_id)
        profile_dir = Path(agent_env["CLAUDE_CONFIG_DIR"])
        memory_scope = f"project-{project_context.id}" if project_context else "personal"
        memory_dir = profile_dir / "eido-memory" / memory_scope
        profile_dir.mkdir(parents=True, exist_ok=True)
        memory_dir.mkdir(parents=True, exist_ok=True)
        auth_problem = auth_error(agent_env)
        if auth_problem:
            logger.error("Claude Agent SDK 认证配置缺失: %s", auth_problem)
            yield self._sse({"type": "error", "message": auth_problem})
            yield "data: [DONE]\n\n"
            return
        auth_mode, provider = auth_summary(agent_env)
        logger.info("  [ClaudeAuth] mode=%s provider=%s", auth_mode, provider)
        project_signature = (
            (
                project_context.id,
                project_context.context_revision,
            )
            if project_context
            else (None, None)
        )
        def _secret_digest(name: str) -> str:
            value = provider_env.get(name, "")
            return hashlib.sha256(value.encode()).hexdigest() if value else ""

        client_signature = (
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

        retrying = False

        async def _run_once(resume_sid: Optional[str]) -> AsyncGenerator[str, None]:
            """单次 SDK 调用，按 resume 模式构建不同 prompt/options。"""
            prompt = build_prompt(
                cwd=cwd,
                skills_dir=self.skills_dir,
                latest_user_text=(
                    "额度已恢复。继续尚未完成的原任务，保留用户追加的要求；先检查已完成步骤，不要重复执行有副作用的操作。"
                    if retrying and resume_sid
                    else latest_user_text
                ),
                context=context,
                resume=bool(resume_sid),
                project_context=project_context,
                conversation_history=(
                    prepare_recovery_context(cwd, user_id, session_id, messages)
                    if not resume_sid
                    else ""
                ),
                native_skills=native_skills,
                fallback_skills_index=(
                    "" if native_skills else self._build_skills_index(user_id=user_id)
                ),
            )
            if latest_user_text.strip().split(maxsplit=1)[0] == "/compact" and not retrying:
                prompt = latest_user_text.strip()
            available_tools = list(self.AUTO_ALLOWED_TOOLS)
            if native_skills:
                available_tools.append("Skill")
            allowed_tools = list(available_tools)
            allowed_tools.extend(f"mcp__{name}__*" for name in mcp_servers)

            async def before_compact(input_data, tool_use_id, hook_context):
                prepare_recovery_context(cwd, user_id, session_id, [])
                return {}

            options = ClaudeAgentOptions(
                model=provider_model,
                effort=settings.CLAUDE_EFFORT,
                cli_path=settings.CLAUDE_CLI_PATH or None,
                system_prompt={
                    "type": "preset",
                    "preset": "claude_code",
                    "append": context_instructions(cwd),
                },
                hooks={"PreCompact": [HookMatcher(hooks=[before_compact])]},
                allowed_tools=allowed_tools,
                tools=available_tools,
                cwd=str(cwd),
                setting_sources=["project"] if native_skills else [],
                skills="all" if native_skills else None,
                permission_mode="acceptEdits",
                # A quota wait may outlive the short-lived task API token.
                env=build_agent_env(
                    user_id,
                    session_id,
                    project_context.id if project_context else None,
                    provider_env=provider_env,
                ),
                include_partial_messages=True,
                max_buffer_size=10 * 1024 * 1024,
                resume=resume_sid,
                mcp_servers=mcp_servers,
                strict_mcp_config=True,
                settings=json.dumps(
                    {
                        "autoMemoryEnabled": True,
                        "autoMemoryDirectory": str(memory_dir),
                    }
                ),
            )
            entry: Optional[ClaudeSessionEntry] = None
            warm_hit = False
            connect_ms = 0.0
            from app.services.claude_event_adapter import ClaudeEventAdapter

            converter = ClaudeEventAdapter()
            message_seen = False
            first_text = False
            rate_reset = None
            rate_rejected = False
            received_result = False
            saw_result = False
            run_started = time.perf_counter()
            try:
                if session_id:
                    try:
                        entry, warm_hit, connect_ms = await self.sessions.acquire(
                            options=options,
                            user_id=user_id,
                            session_id=session_id,
                            signature=client_signature,
                        )
                        await entry.client.query(prompt)
                    except ClaudeSDKError as exc:
                        if resume_sid and self._is_missing_session(exc):
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
                    converter._log_message(message)
                    # Save init SID before the first tool runs, including interrupted turns.
                    from claude_agent_sdk.types import SystemMessage

                    if isinstance(message, SystemMessage) and message.subtype == "init":
                        sid = message.data.get("session_id")
                        if sid:
                            self._save_claude_sid(
                                user_id, session_id, sid, project_context=project_context
                            )
                    from claude_agent_sdk.types import AssistantMessage, RateLimitEvent

                    if isinstance(message, RateLimitEvent):
                        if message.rate_limit_info.status == "rejected":
                            rate_reset = message.rate_limit_info.resets_at
                            rate_rejected = True
                        continue
                    if (
                        isinstance(message, AssistantMessage)
                        and getattr(message, "error", None) == "rate_limit"
                    ):
                        rate_rejected = True
                        continue
                    if is_not_logged_in_message(message):
                        raise _AgentAuthenticationError(AUTH_FAILURE_MESSAGE)
                    # 捕获原生 session_id，持久化以便进程回收/服务重启后 resume
                    try:
                        from claude_agent_sdk.types import ResultMessage  # type: ignore

                        if isinstance(message, ResultMessage):
                            received_result = True
                            saw_result = not message.is_error
                            if session_id and getattr(message, "session_id", None):
                                self._save_claude_sid(
                                    user_id,
                                    session_id,
                                    message.session_id,
                                    project_context=project_context,
                                )
                    except Exception as e:
                        logger.warning(f"持久化 claude_session_id 失败: {e}")
                    if (
                        isinstance(message, ResultMessage)
                        and message.is_error
                        and (rate_rejected or getattr(message, "api_error_status", None) == 429)
                    ):
                        raise _RateLimitPause(rate_reset)
                    for event in converter._convert_message(message):
                        payload = json.loads(event[6:])
                        if payload.get("type") == "error":
                            had_error["v"] = True
                        if payload.get("type") == "content" and not first_text:
                            first_text = True
                            logger.info(
                                "[ClaudeRun] first_text_ms=%.1f warm=%s model=%s",
                                (time.perf_counter() - run_started) * 1000,
                                warm_hit,
                                provider_model,
                            )
                        yield event
                if not received_result:
                    raise RuntimeError("Claude Code 在返回完成状态前断开，会话进度已保留")
            except ClaudeSDKError as exc:
                if resume_sid and not message_seen and self._is_missing_session(exc):
                    raise _ResumeUnavailable(exc) from exc
                raise
            finally:
                if entry is not None:
                    await self.sessions.release(entry, healthy=saw_result)

        # ---- 生产者 + 心跳 桥接到外层 yield ----
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        _SENTINEL = object()

        # 标志：是否发生过 error 事件，决定结束时是否再发 workflow_complete
        had_error = {"v": False}

        async def producer() -> None:
            nonlocal retrying
            resume_sid = claude_sid
            retry_count = 0
            try:
                while True:
                    try:
                        async for ev in _run_once(resume_sid):
                            await queue.put(ev)
                        break
                    except _ResumeUnavailable:
                        if retrying:
                            raise RuntimeError(
                                "限流后原生会话无法恢复，请检查已完成步骤后继续"
                            ) from None
                        self._save_claude_sid(
                            user_id, session_id, None, project_context=project_context
                        )
                        resume_sid = None
                        await queue.put(
                            self._sse(
                                {
                                    "type": "thinking",
                                    "content": "原生会话不可用，正在从完整历史恢复…",
                                }
                            )
                        )
                    except _RateLimitPause as exc:
                        retry_count += 1
                        delay = (
                            max(1, exc.resets_at - time.time() + 1)
                            if exc.resets_at
                            else min(60, 5 * 2 ** min(retry_count - 1, 4))
                        )
                        await queue.put(
                            self._sse(
                                {
                                    "type": "thinking",
                                    "content": (
                                        f"模型额度受限，约 {int(delay)} 秒后自动继续；可随时停止。"
                                    ),
                                }
                            )
                        )
                        deadline = time.monotonic() + delay
                        while time.monotonic() < deadline:
                            await asyncio.sleep(min(60, deadline - time.monotonic()))
                        resume_sid = self._load_claude_sid(
                            user_id, session_id, project_context=project_context
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
                had_error["v"] = True
                await queue.put(self._sse({"type": "error", "message": str(exc)}))
            finally:
                if not asyncio.current_task().cancelling():
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

    @staticmethod
    def _is_missing_session(error: Exception) -> bool:
        text = str(error).lower()
        return any(
            marker in text
            for marker in (
                "no conversation found",
                "session not found",
                "no session found",
                "could not find session",
                "session does not exist",
            )
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

    @staticmethod
    def _sse(data: dict) -> str:
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


# ------------------------------------------------------------------ #
#  全局单例                                                             #
# ------------------------------------------------------------------ #

_instance: Optional[ClaudeRuntime] = None


def get_claude_runtime() -> Optional[ClaudeRuntime]:
    """获取全局单例，startup 完成后才非 None。"""
    return _instance


def init_claude_runtime(skills_dir: Path, workspace_root: Path) -> ClaudeRuntime:
    global _instance
    _instance = ClaudeRuntime(skills_dir, workspace_root)
    logger.info(f"ClaudeRuntime 初始化完成 - 技能目录: {skills_dir}")
    return _instance
