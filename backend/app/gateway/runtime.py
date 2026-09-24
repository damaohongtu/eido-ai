"""Internal endpoints available only in the bound user runtime."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import get_current_user_id
from app.services.chat_execution_guard import get_chat_execution_guard
from app.services.chat_session_store import get_chat_session_store
from app.services.script_runner import run_script
from app.services.session_workspace import get_session_workspace_manager

router = APIRouter()


class ScriptRequest(BaseModel):
    session_id: str
    command: list[str] = Field(min_length=1, max_length=128)


@router.post("/internal/script")
async def execute_script(body: ScriptRequest, user_id: str = Depends(get_current_user_id)):
    session = get_chat_session_store().get_session(user_id, body.session_id)
    if not session:
        raise HTTPException(404, "会话不存在")
    guard = get_chat_execution_guard()
    if not guard.try_acquire(body.session_id, project_id=session.get("project_id")):
        raise HTTPException(409, "会话正在执行")
    try:
        return await run_script(
            body.command, get_session_workspace_manager().session_root(body.session_id)
        )
    finally:
        guard.release(body.session_id)
