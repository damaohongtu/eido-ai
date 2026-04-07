"""
Dependency helpers to resolve current user from Session or signed Token.
"""
from fastapi import HTTPException, Request

from app.core.config import settings
from app.core.user_token import verify_user_token


def get_current_user_id(request: Request) -> str:
    """Resolve user_id: Session cookie > X-Eido-User-Token header."""
    user_id = request.session.get("user_id")
    if user_id:
        return user_id

    token = request.headers.get("X-Eido-User-Token")
    if token:
        try:
            return verify_user_token(token)
        except ValueError:
            raise HTTPException(status_code=401, detail="Token 无效或已过期")

    raise HTTPException(status_code=401, detail="未登录")
