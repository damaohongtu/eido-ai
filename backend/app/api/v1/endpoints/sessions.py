"""
会话（chat session）持久化 REST 接口。

所有接口均按当前登录 user_id 过滤，杜绝越权访问。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import get_current_user_id
from app.services.chat_execution_guard import get_chat_execution_guard
from app.services.chat_session_store import get_chat_session_store
from app.services.project_workspace import validate_project_id
from app.services.session_workspace import (
    get_session_workspace_manager,
    validate_session_id,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class CreateSessionRequest(BaseModel):
    title: Optional[str] = Field(None, description="会话标题，可选")
    skill_id: Optional[str] = Field(None, description="关联的技能 ID，可选")
    project_id: Optional[str] = Field(None, description="所属项目 ID；不传表示普通会话")


class PatchSessionRequest(BaseModel):
    title: Optional[str] = None
    skill_id: Optional[str] = None
    project_id: Optional[str] = None


class AppendMessageRequest(BaseModel):
    role: str = Field(..., description="user / assistant / system")
    content: str = Field(..., description="消息正文")
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="附加字段：thinking / thinkingLog / executionSteps / references / workflowMermaid 等",
    )
    id: Optional[str] = Field(None, description="可选客户端预生成的 message id")


@router.get("/")
async def list_sessions(
    project_id: Optional[str] = Query(None),
    unassigned: bool = Query(False),
    user_id: str = Depends(get_current_user_id),
):
    """返回当前用户的所有会话（按 updated_at 倒序）。"""
    store = get_chat_session_store()
    if project_id and unassigned:
        raise HTTPException(status_code=400, detail="project_id 与 unassigned 不能同时使用")
    if project_id:
        try:
            validate_project_id(project_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if store.get_project(user_id, project_id) is None:
            raise HTTPException(status_code=404, detail="项目不存在")
    return store.list_sessions(user_id, project_id=project_id, unassigned=unassigned)


@router.post("/")
async def create_session(
    body: CreateSessionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """创建新会话；同时落地 session 工作区目录。"""
    store = get_chat_session_store()
    project_guard = None
    project_lease = None
    if body.project_id is not None:
        try:
            validate_project_id(body.project_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        # 先做归属检查，避免持有一个不属于当前用户的 Project 锁；取得共享
        # 租约后仍会再次校验，以覆盖检查与加锁之间的删除/归档窗口。
        project = store.get_project(user_id, body.project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="项目不存在")
        if project.get("archived_at"):
            raise HTTPException(status_code=409, detail="项目已归档，不能新增会话")
        project_guard = get_chat_execution_guard()
        project_lease = project_guard.try_acquire_project_shared(body.project_id)
        if project_lease is None:
            raise HTTPException(status_code=409, detail="项目正在变更，请稍后重试")
    try:
        if body.project_id is not None:
            project = store.get_project(user_id, body.project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="项目不存在")
            if project.get("archived_at"):
                raise HTTPException(status_code=409, detail="项目已归档，不能新增会话")
        try:
            sess = store.create_session(
                user_id,
                title=body.title or "新建会话",
                skill_id=body.skill_id,
                project_id=body.project_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        # 同步创建工作区目录；Project 共享租约覆盖完整创建流程，确保删除端
        # 不会在数据库插入与目录初始化之间取得独占冻结。
        try:
            get_session_workspace_manager().session_root(sess["id"])
        except Exception as e:
            logger.warning(f"创建 session 工作区失败: {e}")
        return sess
    finally:
        if project_guard is not None and project_lease is not None:
            project_guard.release_project(project_lease)


@router.get("/{session_id}")
async def get_session_detail(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """返回会话元信息 + 完整消息列表。"""
    try:
        validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    store = get_chat_session_store()
    sess = store.get_session(user_id, session_id)
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    sess["messages"] = store.list_messages(session_id)
    return sess


@router.patch("/{session_id}")
async def patch_session(
    session_id: str,
    body: PatchSessionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """部分更新会话（标题、关联技能）。"""
    try:
        validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 保留显式传入的 null，允许把 skill_id/project_id 清空。
    fields = body.model_dump(exclude_unset=True)
    store = get_chat_session_store()
    if store.get_session(user_id, session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    target_project_id = fields.get("project_id") if "project_id" in fields else None
    if "project_id" in fields and target_project_id is not None:
        try:
            validate_project_id(target_project_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        target_project = store.get_project(user_id, target_project_id)
        if target_project is None:
            raise HTTPException(status_code=404, detail="目标项目不存在")
        if target_project.get("archived_at"):
            raise HTTPException(status_code=409, detail="目标项目已归档")

    # 只要请求显式修改 project_id，就原子持有 session single-flight 与目标
    # Project 共享租约。这样独占删除无法夹在目标校验和数据库更新之间。
    guard = get_chat_execution_guard() if "project_id" in fields else None
    if guard is not None and not guard.try_acquire(
        session_id, project_id=target_project_id
    ):
        raise HTTPException(
            status_code=409,
            detail="会话正在执行或目标项目正在变更，暂时不能移动项目",
        )
    try:
        existing = store.get_session(user_id, session_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if "project_id" in fields and target_project_id is not None:
            project = store.get_project(user_id, target_project_id)
            if project is None:
                raise HTTPException(status_code=404, detail="目标项目不存在")
            if project.get("archived_at"):
                raise HTTPException(status_code=409, detail="目标项目已归档")
        project_changed = (
            "project_id" in fields
            and existing.get("project_id") != target_project_id
        )
        try:
            sess = store.update_session(user_id, session_id, **fields)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if sess is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        if project_changed:
            # OpenHarness 的上下文只存在内存中；项目切换后必须驱逐旧 engine。
            try:
                from app.services.open_harness_service import get_open_harness_service

                service = get_open_harness_service()
                if service is not None:
                    service.reset_session(session_id)
            except Exception as e:
                logger.warning("重置 OpenHarness 会话失败 session=%s: %s", session_id, e)
        return sess
    finally:
        if guard is not None:
            guard.release(session_id)


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """删除会话 + 消息 + 工作区目录。"""
    try:
        validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    store = get_chat_session_store()
    if store.get_session(user_id, session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    guard = get_chat_execution_guard()
    if not guard.try_acquire(session_id):
        raise HTTPException(status_code=409, detail="会话正在执行，暂时不能删除")
    try:
        deleted = store.delete_session(user_id, session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="会话不存在")
        try:
            get_session_workspace_manager().remove(session_id)
        except Exception as e:
            logger.warning(f"删除 session 工作区失败: {e}")
        return {"deleted": True}
    finally:
        guard.release(session_id)


@router.post("/{session_id}/messages")
async def append_message(
    session_id: str,
    body: AppendMessageRequest,
    user_id: str = Depends(get_current_user_id),
):
    """追加一条消息到指定会话。"""
    try:
        validate_session_id(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if body.role not in ("user", "assistant", "system"):
        raise HTTPException(status_code=400, detail="role 必须是 user/assistant/system")

    store = get_chat_session_store()
    msg = store.append_message(
        user_id,
        session_id,
        role=body.role,
        content=body.content,
        extra=body.extra,
        message_id=body.id,
    )
    if msg is None:
        raise HTTPException(status_code=404, detail="会话不存在或不属于当前用户")
    return msg
