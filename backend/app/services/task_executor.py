"""
Execute scheduled tasks by type: skill, script, chat.

调度位于 gateway 进程（或单租户进程）：
- local 模式：直接调用本进程内的技能服务 / 文件子进程
- docker 模式：先 ensure_running(user_id) 拉起对应用户容器，再发起内部 HTTP
  调用，避免绕过沙箱边界（SQLite / workspace 都在 user 容器里）
"""
import asyncio
import json
import logging
import subprocess
import uuid
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _is_docker_sandbox() -> bool:
    return (settings.EIDO_SANDBOX_MODE or "").lower() == "docker" and not settings.EIDO_TRUST_GATEWAY


async def execute_task(task: dict):
    """Dispatch execution based on task type."""
    task_type = task["type"]
    task_id = task["id"]
    user_id = task["user_id"]
    params = task.get("params", {})

    logger.info(f"[TaskExecutor] 开始执行 task={task_id} type={task_type} user={user_id}")

    try:
        if task_type == "skill":
            if _is_docker_sandbox():
                await _execute_chat_via_sandbox(task_id, user_id, _build_skill_messages(params))
            else:
                await _execute_skill(task_id, user_id, params)
        elif task_type == "script":
            await _execute_script(task_id, params)
        elif task_type == "chat":
            if _is_docker_sandbox():
                msgs = params.get("messages") or []
                await _execute_chat_via_sandbox(task_id, user_id, msgs)
            else:
                await _execute_chat(task_id, user_id, params)
        else:
            logger.error(f"[TaskExecutor] 未知任务类型: {task_type}")
    except Exception:
        logger.exception(f"[TaskExecutor] task={task_id} 执行失败")


def _build_skill_messages(params: dict) -> list[dict]:
    skill_id = params.get("skill_id", "")
    if not skill_id:
        return []
    msg = {"role": "user", "content": f"请执行技能 {skill_id}"}
    extra = params.get("extra_prompt", "")
    if extra:
        msg["content"] += f"\n{extra}"
    return [msg]


async def _execute_skill(task_id: str, user_id: str, params: dict):
    skill_id = params.get("skill_id", "")
    if not skill_id:
        logger.error(f"[TaskExecutor] task={task_id} 缺少 skill_id")
        return

    from app.services.claude_skill_service import get_claude_skill_service

    svc = get_claude_skill_service()
    if not svc:
        logger.error("[TaskExecutor] 技能服务未初始化")
        return

    messages = [{"role": "user", "content": f"请执行技能 {skill_id}"}]
    extra = params.get("extra_prompt", "")
    if extra:
        messages[0]["content"] += f"\n{extra}"

    collected: list[str] = []
    async for chunk in svc.execute_stream(messages, user_id=user_id):
        collected.append(chunk)

    logger.info(f"[TaskExecutor] task={task_id} skill={skill_id} 执行完成, chunks={len(collected)}")


async def _execute_script(task_id: str, params: dict):
    script_path = params.get("script_path", "")
    args = params.get("args", [])
    if not script_path:
        logger.error(f"[TaskExecutor] task={task_id} 缺少 script_path")
        return

    result = await asyncio.to_thread(
        subprocess.run,
        [script_path, *args],
        capture_output=True,
        text=True,
        cwd=settings.WORKSPACE_ROOT,
        timeout=300,
    )
    if result.returncode != 0:
        logger.error(f"[TaskExecutor] task={task_id} script 退出码={result.returncode}\n{result.stderr}")
    else:
        logger.info(f"[TaskExecutor] task={task_id} script 执行成功")


async def _execute_chat(task_id: str, user_id: str, params: dict):
    messages = params.get("messages", [])
    if not messages:
        logger.error(f"[TaskExecutor] task={task_id} 缺少 messages")
        return

    from app.services.claude_skill_service import get_claude_skill_service

    svc = get_claude_skill_service()
    if not svc:
        logger.error("[TaskExecutor] 技能服务未初始化")
        return

    collected: list[str] = []
    async for chunk in svc.execute_stream(messages, user_id=user_id):
        collected.append(chunk)
    logger.info(f"[TaskExecutor] task={task_id} chat 执行完成, chunks={len(collected)}")


async def _execute_chat_via_sandbox(task_id: str, user_id: str, messages: list[dict]):
    """sandbox 模式：通过 gateway → user 容器内部 HTTP 触发 /chat/chat 流式执行。

    - 自动 ensure_running 拉起容器
    - 在 user 容器内借助 sessions API 拿到/创建调度专属会话（标题以 "[scheduled]" 标记）
    - 完整消费 SSE 流以推动后端落库 assistant 输出
    """
    if not messages:
        logger.error(f"[TaskExecutor] task={task_id} 缺少 messages")
        return

    try:
        from app.gateway.sandbox_manager import get_sandbox_manager
        from app.gateway.proxy import get_proxy_client, inject_trust_headers
    except Exception as e:
        logger.error(f"[TaskExecutor] gateway 模块不可用: {e}", exc_info=True)
        return

    mgr = get_sandbox_manager()
    handle = await mgr.ensure_running(user_id)
    client = get_proxy_client()
    base = handle.base_url
    headers = inject_trust_headers({}, user_id)
    headers["Content-Type"] = "application/json"

    # 在 user 容器中创建/复用调度会话
    session_id: Optional[str] = None
    try:
        r = await client.post(
            f"{base}/api/v1/sessions/",
            json={"title": f"[scheduled] {task_id}"},
            headers=headers,
        )
        if r.status_code == 200:
            session_id = r.json().get("id")
    except Exception as e:
        logger.warning(f"[TaskExecutor] 创建调度会话失败: {e}")
        return

    if not session_id:
        logger.warning(f"[TaskExecutor] task={task_id} 无法获取 session_id，放弃")
        return

    payload_msgs = [
        {
            "id": uuid.uuid4().hex[:12],
            "role": m.get("role", "user"),
            "content": m.get("content", ""),
        }
        for m in messages
    ]
    chat_body = {
        "messages": payload_msgs,
        "session_id": session_id,
        "assistant_message_id": uuid.uuid4().hex[:12],
    }

    try:
        async with client.stream(
            "POST",
            f"{base}/api/v1/chat/chat",
            headers=headers,
            json=chat_body,
        ) as resp:
            chunks = 0
            async for _ in resp.aiter_bytes():
                chunks += 1
        logger.info(f"[TaskExecutor] task={task_id} via sandbox 完成 chunks={chunks}")
    except Exception:
        logger.exception(f"[TaskExecutor] task={task_id} via sandbox 失败")
