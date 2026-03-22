"""
确保数据库中有默认用户
用于开发环境，避免用户认证导致的约束错误
"""
import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import select
from app.core.database import async_session_maker
from app.models.user import User
import uuid

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"

async def ensure_default_user():
    """确保默认用户存在"""
    async with async_session_maker() as session:
        # 检查默认用户是否存在
        result = await session.execute(
            select(User).where(User.id == uuid.UUID(DEFAULT_USER_ID))
        )
        user = result.scalar_one_or_none()
        
        if user:
            print(f"✓ 默认用户已存在: {user.username}")
            return user.id
        
        # 创建默认用户
        user = User(
            id=uuid.UUID(DEFAULT_USER_ID),
            username="default_user",
            email="default@eido.local",
            password_hash="not_used_in_dev",  # 开发环境不使用密码
            role="USER",
            bio="默认开发用户"
        )
        
        session.add(user)
        await session.commit()
        print(f"✓ 已创建默认用户: {user.username} (ID: {user.id})")
        return user.id

if __name__ == "__main__":
    asyncio.run(ensure_default_user())
