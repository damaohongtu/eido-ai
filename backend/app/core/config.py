"""
Configuration management for the application.
"""
from pathlib import Path
from pydantic import field_validator
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

    # CAS / Session
    AUTH_DISABLED: bool = False
    DEFAULT_DEV_USER_ID: str = "dev-local"
    # 须含 /cas 路径；末尾必须有 /，否则 python-cas 用 urljoin 会错误拼成 http://host/login
    CAS_SERVER_URL: str = "http://localhost:3331/cas/"
    CAS_SERVICE_URL: str = "http://localhost:8000/api/v1/auth/callback"
    CAS_VERSION: str = "2"
    FRONTEND_URL: str = "http://localhost:3000/ai-eido/"
    SESSION_SECRET_KEY: str = "dev-secret-change-in-production"

    # Scheduled tasks & signed token
    SCHEDULED_TASKS_DB: str = ""
    EIDO_USER_TOKEN_SECRET: str = ""
    EIDO_USER_TOKEN_TTL: int = 300

    # Logging Configuration
    LOG_LEVEL: str = "INFO"

    @property
    def scheduled_tasks_db_path(self) -> Path:
        if self.SCHEDULED_TASKS_DB.strip():
            return Path(self.SCHEDULED_TASKS_DB)
        return Path(self.WORKSPACE_ROOT) / ".eido" / "scheduled_tasks.db"

    @property
    def token_secret(self) -> str:
        return self.EIDO_USER_TOKEN_SECRET.strip() or self.SESSION_SECRET_KEY

    @field_validator("CAS_SERVER_URL", mode="before")
    @classmethod
    def normalize_cas_server_url(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            return v
        return v.rstrip("/") + "/"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()

