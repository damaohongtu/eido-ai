"""
Configuration management for the application.
"""
from pathlib import Path
from pydantic_settings import BaseSettings

# 工作区根目录（backend/app/core/ → backend/app/ → backend/ → workspace/）
_WORKSPACE_ROOT = Path(__file__).parents[3]


class Settings(BaseSettings):
    """Application settings with validation."""

    # API Configuration
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Eido AI Backend"
    VERSION: str = "1.0.0"

    # CORS Configuration（allow_credentials=True 时不能使用 "*"，需明确列出 origin）
    BACKEND_CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ]

    DEBUG: bool = False

    # Skills Configuration
    SKILLS_DIR: str = str(_WORKSPACE_ROOT / ".claude" / "skills")
    WORKSPACE_ROOT: str = str(_WORKSPACE_ROOT)

    # Logging Configuration
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()

