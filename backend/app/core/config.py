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

    # ---------------- Per-user sandbox / data isolation ---------------- #
    # 数据根目录。沙箱容器内由 gateway 注入 `/data`；本机/兼容部署留空，回退到
    # WORKSPACE_ROOT/.eido。
    EIDO_DATA_ROOT: str = ""
    # 显式覆盖 chat_sessions.db 路径，沙箱模式下指向 /data/chat_sessions.db。
    CHAT_SESSIONS_DB: str = ""
    # 沙箱模式：local | docker（gateway 端使用，user 容器无需关心）
    EIDO_SANDBOX_MODE: str = "local"
    # gateway 用于启动 user 容器的镜像 tag
    EIDO_USER_IMAGE: str = "eido-user:latest"
    # gateway / user 共享的 docker 网络
    EIDO_NET: str = "eido-net"
    # 闲置回收 TTL（秒），默认 15min
    EIDO_SANDBOX_IDLE_TTL: int = 900
    # gateway 持久化 sandbox 注册表的 SQLite
    SANDBOX_REGISTRY_DB: str = ""
    # 资源限额
    EIDO_USER_MEM: str = "2g"
    EIDO_USER_CPUS: float = 1.0
    EIDO_USER_PIDS_LIMIT: int = 500
    # 逗号分隔；gateway 拉起 eido-user 时写入容器 dns，供内网域名解析（留空则用 Docker 默认）
    EIDO_DNS_SERVERS: str = ""

    # gateway → user 共享 secret，user 容器进入"信任网关头"模式必须校验该值
    EIDO_GATEWAY_SECRET: str = ""
    # user 容器内开关：仅在沙箱模式下置 1
    EIDO_TRUST_GATEWAY: bool = False
    # user 容器绑定的 user_id（容器启动时注入）
    EIDO_USER_ID: str = ""
    # gateway 内部访问 user 容器使用的端口（容器内监听 8000）
    EIDO_USER_INTERNAL_PORT: int = 8000

    # 管理员白名单（逗号分隔 user_id），命中者上传/修改的技能写入 system 区
    EIDO_ADMIN_USERS: str = ""

    # Logging Configuration
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "logs"

    @property
    def data_root(self) -> Path:
        """统一的数据根目录。沙箱容器：/data；本机：<workspace>/.eido"""
        if self.EIDO_DATA_ROOT.strip():
            return Path(self.EIDO_DATA_ROOT)
        return Path(self.WORKSPACE_ROOT) / ".eido"

    @property
    def chat_sessions_db_path(self) -> Path:
        if self.CHAT_SESSIONS_DB.strip():
            return Path(self.CHAT_SESSIONS_DB)
        return self.data_root / "chat_sessions.db"

    @property
    def scheduled_tasks_db_path(self) -> Path:
        if self.SCHEDULED_TASKS_DB.strip():
            return Path(self.SCHEDULED_TASKS_DB)
        return self.data_root / "scheduled_tasks.db"

    @property
    def sandbox_registry_db_path(self) -> Path:
        if self.SANDBOX_REGISTRY_DB.strip():
            return Path(self.SANDBOX_REGISTRY_DB)
        return self.data_root / "sandbox_registry.db"

    @property
    def workspaces_root(self) -> Path:
        """会话工作区根目录：<data_root>/workspaces。"""
        return self.data_root / "workspaces"

    @property
    def token_secret(self) -> str:
        return self.EIDO_USER_TOKEN_SECRET.strip() or self.SESSION_SECRET_KEY

    @property
    def eido_user_dns_list(self) -> list[str]:
        """从内网 DNS 环境变量解析出的 IP 列表，供 sandbox user 容器使用。"""
        raw = (self.EIDO_DNS_SERVERS or "").strip()
        if not raw:
            return []
        parts = []
        for p in raw.split(","):
            s = p.strip()
            if s:
                parts.append(s)
        return parts

    @property
    def admin_user_set(self) -> set[str]:
        """admin 白名单（逗号分隔）的集合形式。"""
        return {u.strip() for u in (self.EIDO_ADMIN_USERS or "").split(",") if u.strip()}

    def is_admin(self, user_id: str | None) -> bool:
        """判断给定 user_id 是否在 admin 白名单内。"""
        if not user_id:
            return False
        return user_id in self.admin_user_set

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

