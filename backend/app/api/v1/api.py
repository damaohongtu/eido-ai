"""
API router aggregator for v1 endpoints.
"""
from fastapi import APIRouter
from app.api.v1.endpoints import auth, chat, sessions, tasks, workflow, skills, workspace

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(workflow.router, prefix="/workflow", tags=["workflow"])
api_router.include_router(skills.router, prefix="/skills", tags=["skills"])
api_router.include_router(workspace.router, prefix="/workspace", tags=["workspace"])

