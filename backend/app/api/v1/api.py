"""
API router aggregator for v1 endpoints.

布局思路：
- gateway / 单租户模式（默认）：聚合所有路由 — auth, chat, sessions, workspace, skills, tasks, workflow
- sandbox 模式（gateway 启用 docker，EIDO_SANDBOX_MODE=docker）：
  gateway 进程把 chat/sessions/workspace/upload 替换成 router_user 反代到用户容器；
  其余路由（auth, skills, tasks, workflow）继续走 gateway 自身。

user 沙箱容器内：路由聚合走 _user_only_router()，仅保留 chat / sessions / workspace。
"""
from fastapi import APIRouter

from app.core.config import settings
from app.api.v1.endpoints import auth, chat, sessions, tasks, workflow, skills, workspace


def _is_user_sandbox_runtime() -> bool:
    """user 容器以 EIDO_TRUST_GATEWAY=1 启动；该开关为 True 即视为 user runtime。"""
    return bool(settings.EIDO_TRUST_GATEWAY)


def _is_gateway_sandbox_mode() -> bool:
    return (settings.EIDO_SANDBOX_MODE or "").lower() == "docker"


api_router = APIRouter()


if _is_user_sandbox_runtime():
    # eido-user 容器：仅暴露业务执行路由
    api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
    api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
    api_router.include_router(workspace.router, prefix="/workspace", tags=["workspace"])
elif _is_gateway_sandbox_mode():
    # eido-gateway：业务路由用反代，其它路由直连
    from app.gateway import router_user  # 延迟导入，避免单镜像部署时强依赖 docker SDK

    api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
    api_router.include_router(skills.router, prefix="/skills", tags=["skills"])
    api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
    api_router.include_router(workflow.router, prefix="/workflow", tags=["workflow"])
    api_router.include_router(router_user.router, tags=["sandbox-proxy"])
else:
    # 默认/单租户：保留原有聚合
    api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
    api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
    api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
    api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
    api_router.include_router(workflow.router, prefix="/workflow", tags=["workflow"])
    api_router.include_router(skills.router, prefix="/skills", tags=["skills"])
    api_router.include_router(workspace.router, prefix="/workspace", tags=["workspace"])

    # 让单租户也支持 sandbox/warmup（no-op）以便前端代码逻辑统一
    @api_router.post("/sandbox/warmup", tags=["sandbox"])
    async def _warmup_local():
        return {"ready": True, "mode": "local"}

