"""
Workflow endpoints（已简化）

LangGraph 工作流已由 claude_agent_sdk 取代，此文件仅保留路由占位以保持 API 路由注册不变。
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def workflow_health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "workflow"}
