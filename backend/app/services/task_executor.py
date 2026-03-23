"""
Execute scheduled tasks by type: skill, script, chat.
"""
import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


async def execute_task(task: dict):
    """Dispatch execution based on task type."""
    task_type = task["type"]
    task_id = task["id"]
    user_id = task["user_id"]
    params = task.get("params", {})

    logger.info(f"[TaskExecutor] 开始执行 task={task_id} type={task_type} user={user_id}")

    try:
        if task_type == "skill":
            await _execute_skill(task_id, user_id, params)
        elif task_type == "script":
            await _execute_script(task_id, params)
        elif task_type == "chat":
            await _execute_chat(task_id, user_id, params)
        else:
            logger.error(f"[TaskExecutor] 未知任务类型: {task_type}")
    except Exception:
        logger.exception(f"[TaskExecutor] task={task_id} 执行失败")


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
