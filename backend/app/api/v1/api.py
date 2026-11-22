"""Register public, proxied and sandbox-only routes for the current role."""

from fastapi import APIRouter, Depends

from app.api.v1.endpoints import (
    auth,
    chat,
    mcp,
    projects,
    search,
    sessions,
    skills,
    tasks,
    workspace,
)
from app.core.config import settings

api_router = APIRouter()

if not settings.EIDO_TRUST_GATEWAY:
    api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
    api_router.include_router(skills.router, prefix="/skills", tags=["skills"])
    api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])

if settings.is_gateway_role:
    from app.gateway import provider, router_user

    api_router.include_router(provider.router, tags=["provider"])
    api_router.include_router(router_user.router, tags=["sandbox-proxy"])
    api_router.add_api_route(
        "/chat/models",
        chat.list_models,
        methods=["GET"],
        tags=["sandbox-proxy"],
        dependencies=[Depends(router_user.resolve_user_id)],
    )
    legacy_chat_endpoint = router_user.proxy_chat_chat
else:
    legacy_chat_endpoint = chat.chat_completion
    for prefix, endpoints in (
        ("chat", chat),
        ("sessions", sessions),
        ("projects", projects),
        ("workspace", workspace),
        ("mcp", mcp),
        ("search", search),
    ):
        api_router.include_router(endpoints.router, prefix=f"/{prefix}", tags=[prefix])

    if settings.EIDO_TRUST_GATEWAY:
        from app.gateway.runtime import router as runtime_router

        api_router.include_router(runtime_router, tags=["internal"])
    else:

        @api_router.post("/sandbox/warmup", tags=["sandbox"])
        async def _warmup_local():
            return {"ready": True, "mode": "local"}
