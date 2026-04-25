"""
Gateway → user 沙箱 反代路由。

当 EIDO_SANDBOX_MODE=docker 时，main 应用会改用本路由代替原来的
chat / sessions / workspace 直连业务逻辑：
- 入口仍解析 user_id（CAS session / Token / 受信网关头都不适用，但 gateway 自身
  以 CAS session 为准）
- ensure_running(user_id) 后获得容器内部地址
- proxy_request 透传请求与响应（含 SSE）
"""
from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.auth import get_current_user_id
from app.gateway.proxy import proxy_request
from app.gateway.sandbox_manager import get_sandbox_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# user_id 入口白名单：避免被恶意构造拼到 docker 容器名 / 路径里
_USER_ID_RE = re.compile(r"^[A-Za-z0-9._@\-]{1,128}$")


async def resolve_user_id(user_id: str = Depends(get_current_user_id)) -> str:
    """Auth 之后再做一次格式校验，杜绝奇异字符流入沙箱编排逻辑。"""
    if not user_id or not _USER_ID_RE.match(user_id):
        logger.warning("非法 user_id 入站: %r", user_id)
        raise HTTPException(status_code=400, detail="非法 user_id 格式")
    return user_id


# ----------------------------- chat ----------------------------- #

@router.post("/chat/chat")
async def proxy_chat_chat(request: Request, user_id: str = Depends(resolve_user_id)):
    handle = await get_sandbox_manager().ensure_running(user_id)
    return await proxy_request(request, handle, upstream_path="/api/v1/chat/chat")


@router.post("/chat/upload")
async def proxy_chat_upload(request: Request, user_id: str = Depends(resolve_user_id)):
    handle = await get_sandbox_manager().ensure_running(user_id)
    return await proxy_request(request, handle, upstream_path="/api/v1/chat/upload")


@router.get("/chat/health")
async def proxy_chat_health(request: Request, user_id: str = Depends(resolve_user_id)):
    handle = await get_sandbox_manager().ensure_running(user_id)
    return await proxy_request(request, handle, upstream_path="/api/v1/chat/health")


# --------------------------- sessions --------------------------- #

@router.api_route("/sessions/", methods=["GET", "POST"])
async def proxy_sessions_root(request: Request, user_id: str = Depends(resolve_user_id)):
    handle = await get_sandbox_manager().ensure_running(user_id)
    return await proxy_request(request, handle, upstream_path="/api/v1/sessions/")


@router.api_route("/sessions/{rest:path}", methods=["GET", "POST", "PATCH", "DELETE", "PUT"])
async def proxy_sessions_rest(
    rest: str, request: Request, user_id: str = Depends(resolve_user_id)
):
    handle = await get_sandbox_manager().ensure_running(user_id)
    return await proxy_request(request, handle, upstream_path=f"/api/v1/sessions/{rest}")


# --------------------------- workspace --------------------------- #

@router.get("/workspace/file")
async def proxy_workspace_file(request: Request, user_id: str = Depends(resolve_user_id)):
    handle = await get_sandbox_manager().ensure_running(user_id)
    return await proxy_request(request, handle, upstream_path="/api/v1/workspace/file")


# --------------------------- sandbox warmup --------------------------- #

@router.post("/sandbox/warmup")
async def warmup_sandbox(user_id: str = Depends(resolve_user_id)):
    """登录后调用，提前拉起 user 容器。返回 handle 元数据（不暴露内部 host）。"""
    handle = await get_sandbox_manager().ensure_running(user_id)
    return {
        "user_id": user_id,
        "container": handle.container_name,
        "status": handle.status,
        "ready": True,
    }


@router.get("/sandbox/status")
async def sandbox_status(user_id: str = Depends(resolve_user_id)):
    mgr = get_sandbox_manager()
    row = mgr._select_row(user_id)  # noqa: SLF001
    if not row:
        return {"user_id": user_id, "running": False}
    return {
        "user_id": user_id,
        "running": (row["status"] == "running"),
        "container": row["container_name"],
        "last_active_at": row["last_active_at"],
    }
