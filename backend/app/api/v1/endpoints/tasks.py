"""
Task CRUD endpoints.
User identity resolved from Session cookie or signed X-Eido-User-Token header.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import get_current_user_id
from app.services import scheduler_service
from app.services.scheduled_task_store import ScheduledTaskStore

router = APIRouter()
logger = logging.getLogger(__name__)

_store: ScheduledTaskStore | None = None


def set_store(store: ScheduledTaskStore):
    global _store
    _store = store


def _get_store() -> ScheduledTaskStore:
    if _store is None:
        raise HTTPException(status_code=503, detail="任务存储未初始化")
    return _store


class TaskCreate(BaseModel):
    name: str
    schedule: str
    type: str = Field(pattern=r"^(skill|script|chat)$")
    params: dict = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    schedule: Optional[str] = None
    type: Optional[str] = None
    params: Optional[dict] = None
    enabled: Optional[bool] = None


@router.get("/")
async def list_tasks(
    enabled: Optional[bool] = None,
    user_id: str = Depends(get_current_user_id),
):
    store = _get_store()
    return store.list_tasks(user_id, enabled=enabled)


@router.post("/")
async def create_task(
    body: TaskCreate,
    user_id: str = Depends(get_current_user_id),
):
    store = _get_store()
    task = store.create(user_id, body.name, body.schedule, body.type, body.params)
    scheduler_service.add_job(task)
    logger.info(f"[{user_id}] 创建任务: {task['id']} name={task['name']}")
    return task


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
):
    store = _get_store()
    task = store.get(user_id, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


@router.patch("/{task_id}")
async def update_task(
    task_id: str,
    body: TaskUpdate,
    user_id: str = Depends(get_current_user_id),
):
    store = _get_store()
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="无更新字段")

    task = store.update(user_id, task_id, **fields)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    scheduler_service.remove_job(task_id)
    if task["enabled"]:
        scheduler_service.add_job(task)

    logger.info(f"[{user_id}] 更新任务: {task_id}")
    return task


@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
):
    store = _get_store()
    ok = store.delete(user_id, task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在")
    scheduler_service.remove_job(task_id)
    logger.info(f"[{user_id}] 删除任务: {task_id}")
    return {"ok": True}


@router.post("/{task_id}/run")
async def run_task(
    task_id: str,
    user_id: str = Depends(get_current_user_id),
):
    store = _get_store()
    task = store.get(user_id, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")

    from app.services.task_executor import execute_task
    import asyncio
    asyncio.create_task(execute_task(task))
    logger.info(f"[{user_id}] 手动触发任务: {task_id}")
    return {"ok": True, "message": "任务已触发"}
