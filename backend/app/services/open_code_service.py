"""OpenCode CLI 执行服务，适配 Eido 统一的 ``execute_stream``/SSE 接口。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import AsyncGenerator, Optional

from app.gateway.sandbox_manager import _safe_user_id
from app.services.conversation_context import format_recent_conversation
from app.services.project_context import ProjectContext, format_project_context

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SEC = 12.0
_HEARTBEAT_FRAME = ": ping\n\n"


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _latest_user_text(messages: list) -> str:
    for message in reversed(messages or []):
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        if isinstance(message, dict):
            role, content = message.get("role"), message.get("content")
        if role == "user":
            return (content or "").strip()
    return ""


def _event_error_message(event: dict) -> str:
    error = event.get("error")
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        data = error.get("data")
        if isinstance(data, dict) and data.get("message"):
            return str(data["message"])
        return str(error.get("message") or error.get("name") or error)
    return "OpenCode 执行失败"


def _convert_event(event: dict) -> list[str]:
    """把 ``opencode run --format json`` 的一行事件转换为 Eido SSE。"""
    event_type = event.get("type")
    part = event.get("part") if isinstance(event.get("part"), dict) else {}

    if event_type == "text" and part.get("text"):
        return [_sse({"type": "content", "content": part["text"]})]
    if event_type == "reasoning" and part.get("text"):
        return [_sse({"type": "thinking", "content": part["text"]})]
    if event_type == "step_start":
        return [_sse({"type": "thinking", "content": "OpenCode 开始执行步骤..."})]
    if event_type == "step_finish":
        return [_sse({"type": "thinking", "content": "OpenCode 步骤执行完成"})]
    if event_type == "tool_use":
        tool = str(part.get("tool") or "tool")
        state = part.get("state") if isinstance(part.get("state"), dict) else {}
        if state.get("status") == "error":
            detail = str(state.get("error") or "")[:240]
            return [_sse({"type": "thinking", "content": f"✗ 工具失败: {tool}{': ' + detail if detail else ''}"})]
        return [_sse({"type": "thinking", "content": f"✓ 工具完成: {tool}"})]
    if event_type == "error":
        return [_sse({"type": "error", "message": _event_error_message(event)})]
    return []


class OpenCodeService:
    """为每个 Eido 会话调用 OpenCode CLI，并用原生 session ID 续接多轮对话。"""

    def __init__(self, skills_dir: Path, workspace_root: Path, binary: str = "opencode"):
        self.skills_dir = skills_dir
        self.workspace_root = workspace_root
        self.binary = binary
        if not shutil.which(binary):
            raise RuntimeError(
                "OpenCode CLI 未安装，请运行: npm install -g opencode-ai"
            )

    def _skills_index(self, user_id: Optional[str]) -> str:
        roots = [self.skills_dir / "system"]
        if user_id:
            roots.append(self.skills_dir / "users" / _safe_user_id(user_id))
        skills: dict[str, Path] = {}
        for root in roots:
            if not root.exists():
                continue
            for skill_file in sorted(root.glob("*/SKILL.md")):
                skills[skill_file.parent.name] = skill_file.resolve()
        if not skills:
            return "（当前没有可用技能）"
        return "\n".join(f"- {name}: `{path}`" for name, path in sorted(skills.items()))

    def _build_prompt(
        self,
        text: str,
        cwd: Path,
        context: Optional[str],
        user_id: Optional[str],
        *,
        resume: bool,
        project_context: Optional[ProjectContext] = None,
        conversation_history: str = "",
    ) -> str:
        context_section = ""
        if context and context.strip():
            context_section = f"\n\n---\n## 上一步执行结果（供参考）\n{context.strip()[:4000]}"
        project_text = format_project_context(project_context)
        project_section = f"{project_text}\n\n---\n\n" if project_text else ""
        history_section = (
            f"{conversation_history}\n\n---\n\n" if conversation_history else ""
        )
        if resume:
            return f"{project_section}## 用户最新请求\n{text}{context_section}"
        return (
            f"当前会话工作区是 `{cwd}`。上传文件位于 `{cwd / 'uploads'}`，"
            f"所有生成产物必须写入 `{cwd / 'outputs'}`。\n\n"
            f"{project_section}"
            f"## 可用技能\n{self._skills_index(user_id)}\n\n"
            "需要技能时，先使用 skill 工具或读取上面对应的 SKILL.md，并严格遵循技能说明。"
            "不要把产物写到会话工作区之外。\n\n"
            f"{history_section}"
            f"## 用户最新请求\n{text}{context_section}"
        )

    @staticmethod
    def _load_session_id(
        user_id: Optional[str],
        session_id: Optional[str],
        *,
        project_context: Optional[ProjectContext],
    ) -> Optional[str]:
        if not (user_id and session_id):
            return None
        try:
            from app.services.chat_session_store import get_chat_session_store
            return get_chat_session_store().get_opencode_session_id(
                user_id,
                session_id,
                expected_project_id=project_context.id if project_context else None,
                expected_context_revision=(
                    project_context.context_revision if project_context else None
                ),
            )
        except Exception as exc:
            logger.warning("读取 opencode_session_id 失败: %s", exc)
            return None

    @staticmethod
    def _save_session_id(
        user_id: Optional[str],
        session_id: Optional[str],
        opencode_session_id: str,
        *,
        project_context: Optional[ProjectContext],
    ) -> None:
        if not (user_id and session_id):
            return
        try:
            from app.services.chat_session_store import get_chat_session_store
            saved = get_chat_session_store().set_opencode_session_id(
                user_id,
                session_id,
                opencode_session_id,
                expected_project_id=project_context.id if project_context else None,
                expected_context_revision=(
                    project_context.context_revision if project_context else None
                ),
            )
            if not saved:
                logger.info(
                    "忽略已过期请求返回的 OpenCode session ID: session=%s",
                    session_id,
                )
        except Exception as exc:
            logger.warning("持久化 opencode_session_id 失败: %s", exc)

    async def execute_stream(
        self, messages: list, context: Optional[str] = None, *,
        user_id: Optional[str] = None, session_id: Optional[str] = None,
        project_context: Optional[ProjectContext] = None,
    ) -> AsyncGenerator[str, None]:
        yield _sse({"type": "thinking", "content": "正在通过 OpenCode 分析请求..."})
        yield _sse({"type": "workflow_start", "skill_name": "auto"})

        text = _latest_user_text(messages)
        if not text:
            yield _sse({"type": "error", "message": "未找到用户输入"})
            yield "data: [DONE]\n\n"
            return
        recent_history = format_recent_conversation(messages)

        if session_id:
            from app.services.session_workspace import get_session_workspace_manager
            try:
                cwd = get_session_workspace_manager().session_root(session_id)
            except ValueError as exc:
                yield _sse({"type": "error", "message": f"非法 session_id: {exc}"})
                yield "data: [DONE]\n\n"
                return
        else:
            cwd = self.workspace_root

        native_session_id = self._load_session_id(
            user_id, session_id, project_context=project_context
        )
        prompt = self._build_prompt(
            text,
            cwd,
            context,
            user_id,
            resume=bool(native_session_id),
            project_context=project_context,
            conversation_history=recent_history,
        )
        args = [self.binary, "run", "--format", "json", "--auto", "--dir", str(cwd)]
        model = os.environ.get("OPENCODE_MODEL", "").strip()
        if model:
            args.extend(["--model", model])
        if native_session_id:
            args.extend(["--session", native_session_id])
        args.append(prompt)

        env = os.environ.copy()
        # user sandbox 会被闲置回收并重建；把 OpenCode 的原生会话数据库放进 /data，
        # 否则 chat_sessions 中的原生 session ID 会指向已丢失的容器文件。
        from app.core.config import settings
        if settings.EIDO_DATA_ROOT.strip():
            env.setdefault(
                "XDG_DATA_HOME", str(Path(settings.EIDO_DATA_ROOT) / "opencode-data")
            )
        if user_id:
            from app.core.user_token import create_user_token
            env["EIDO_USER_TOKEN"] = create_user_token(user_id)
        if session_id:
            env["EIDO_SESSION_ID"] = session_id
        if project_context:
            env["EIDO_PROJECT_ID"] = project_context.id

        queue: asyncio.Queue[object] = asyncio.Queue()
        done = object()
        state = {"had_error": False}
        process: Optional[asyncio.subprocess.Process] = None

        async def producer() -> None:
            nonlocal process
            stderr_text = ""
            try:
                process = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=str(cwd),
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                async def read_stderr() -> str:
                    assert process and process.stderr
                    return (await process.stderr.read()).decode("utf-8", errors="replace")

                stderr_task = asyncio.create_task(read_stderr())
                assert process.stdout
                while line := await process.stdout.readline():
                    raw = line.decode("utf-8", errors="replace").strip()
                    if not raw:
                        continue
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        logger.debug("忽略 OpenCode 非 JSON 输出: %s", raw[:240])
                        continue
                    sid = event.get("sessionID")
                    if isinstance(sid, str) and sid:
                        self._save_session_id(
                            user_id,
                            session_id,
                            sid,
                            project_context=project_context,
                        )
                    for converted in _convert_event(event):
                        if event.get("type") == "error":
                            state["had_error"] = True
                        await queue.put(converted)
                return_code = await process.wait()
                stderr_text = await stderr_task
                if return_code != 0 and not state["had_error"]:
                    state["had_error"] = True
                    detail = stderr_text.strip()[-1000:] or f"退出码 {return_code}"
                    await queue.put(_sse({"type": "error", "message": f"OpenCode 执行失败: {detail}"}))
            except asyncio.CancelledError:
                if process and process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                raise
            except Exception as exc:
                state["had_error"] = True
                logger.error("OpenCode 执行异常: %s", exc, exc_info=True)
                await queue.put(_sse({"type": "error", "message": f"OpenCode 执行失败: {exc}"}))
            finally:
                await queue.put(done)

        async def heartbeat() -> None:
            try:
                while True:
                    await asyncio.sleep(HEARTBEAT_INTERVAL_SEC)
                    await queue.put(_HEARTBEAT_FRAME)
            except asyncio.CancelledError:
                pass

        producer_task = asyncio.create_task(producer())
        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            while True:
                event = await queue.get()
                if event is done:
                    break
                yield str(event)
            if not state["had_error"]:
                yield _sse({"type": "workflow_complete", "data": {"references": []}})
        finally:
            heartbeat_task.cancel()
            if not producer_task.done():
                producer_task.cancel()
            for task in (heartbeat_task, producer_task):
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        yield "data: [DONE]\n\n"


_instance: Optional[OpenCodeService] = None


def get_open_code_service() -> Optional[OpenCodeService]:
    return _instance


def init_open_code_service(skills_dir: Path, workspace_root: Path) -> OpenCodeService:
    global _instance
    _instance = OpenCodeService(skills_dir, workspace_root)
    logger.info("OpenCodeService 初始化完成 - 技能目录: %s", skills_dir)
    return _instance
