"""
会话（chat session）持久化 REST 接口。

所有接口均按当前登录 user_id 过滤，杜绝越权访问。
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.auth import get_current_user_id
from app.services.chat_session_store import get_chat_session_store
from app.services.session_workspace import (
    get_session_workspace_manager,
    validate_session_id,
)

router = APIRouter()
logger = logging.getLogger(__name__)


class CreateSessionRequest(BaseModel):
    title: Optional[str] = Field(None, description="会话标题，可选")
    skill_id: Optional[str] = Field(None, description="关联的技能 ID，可选")


class PatchSessionRequest(BaseModel):
    title: Optional[str] = None
    skill_id: Optional[str] = None


class AppendMessageRequest(BaseModel):
    role: str = Field(..., description="user / assistant / system")
    content: str = Field(..., description="消息正文")
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="附加字段：thinking / thinkingLog / executionSteps / references / workflowMermaid 等",
    )
    id: Optional[str] = Field(None, description="可选客户端预生成的 message id")


@router.get("/")
async def list_sessions(user_id: str = Depends(get_current_user_id)):
    """返回当前用户的所有会话（按 updated_at 倒序）。"""
    store = get_chat_session_store()
    return store.list_sessions(user_id)


@router.post("/")
async def create_session(
    body: CreateSessionRequest,
    user_id: str = Depends(get_current_user_id),
):
    """创建新会话；同时落地 session 工作区目录。"""
    store = get_chat_session_store()
    sess = store.create_session(
        user_id,
        title=body.title or "新建会话",
        skill_id=body.skill_id,
    )
    # 同步创建工作区目录
    try:
        get_session_workspace_manager().session_root(sess["id"])
    except Exception as e:
        logger.warning(f"创建 session 工作区失败: {e}")
    return sess


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
    # 保留显式传入的 null，允许把 skill_id 清空。
    fields = body.model_dump(exclude_unset=True)
    store = get_chat_session_store()
    sess = store.update_session(user_id, session_id, **fields)
    if sess is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return sess


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
    deleted = store.delete_session(user_id, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        get_session_workspace_manager().remove(session_id)
    except Exception as e:
        logger.warning(f"删除 session 工作区失败: {e}")
    return {"deleted": True}


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
