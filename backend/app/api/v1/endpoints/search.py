"""Unified project and conversation search."""
from fastapi import APIRouter, Depends, Query

from app.core.auth import get_current_user_id
from app.services.chat_session_store import get_chat_session_store

router = APIRouter()


@router.get("")
async def search_navigation(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=50),
    user_id: str = Depends(get_current_user_id),
):
    return get_chat_session_store().search_navigation(user_id, q, limit=limit)
