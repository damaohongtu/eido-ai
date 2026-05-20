"""
Main FastAPI application entrypoint.
"""
import shutil
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from app.core.config import settings
from app.api.v1.api import api_router
import logging
from logging.handlers import TimedRotatingFileHandler
import time
from pathlib import Path


def _migrate_legacy_skills(skills_dir: Path) -> None:
    """把旧的扁平 SKILLS_DIR/<id> 目录迁移到 SKILLS_DIR/system/<id>。

    幂等：仅迁移 SKILLS_DIR 顶层中含 SKILL.md 的子目录；system/、users/、
    其他非技能文件保持原状。
    """
    if not skills_dir.exists():
        return
    system_dir = skills_dir / "system"
    users_dir = skills_dir / "users"
    try:
        system_dir.mkdir(parents=True, exist_ok=True)
        users_dir.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logging.getLogger(__name__).warning("准备 skills 子目录失败: %s", e)
        return

    moved = 0
    for entry in skills_dir.iterdir():
        if entry.name in ("system", "users"):
            continue
        if not entry.is_dir():
            continue
        if not (entry / "SKILL.md").exists():
            continue
        target = system_dir / entry.name
        if target.exists():
            logging.getLogger(__name__).info(
                "跳过迁移（system 区已存在同名）: %s", entry.name
            )
            continue
        try:
            shutil.move(str(entry), str(target))
            moved += 1
        except Exception as e:
            logging.getLogger(__name__).warning(
                "迁移技能失败 %s: %s", entry.name, e
            )
    if moved:
        logging.getLogger(__name__).info(
            "已迁移 %d 个旧技能目录到 %s", moved, system_dir
        )

log_dir = Path(settings.LOG_DIR)
log_dir.mkdir(parents=True, exist_ok=True)

detailed_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

root_logger = logging.getLogger()
root_logger.setLevel(settings.LOG_LEVEL)

console_handler = logging.StreamHandler()
console_handler.setLevel(settings.LOG_LEVEL)
console_handler.setFormatter(detailed_formatter)

file_handler = TimedRotatingFileHandler(
    log_dir / 'app.log', when='midnight', backupCount=7, encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(detailed_formatter)
file_handler.suffix = '%Y-%m-%d'

error_handler = TimedRotatingFileHandler(
    log_dir / 'error.log', when='midnight', backupCount=7, encoding='utf-8'
)
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(detailed_formatter)
error_handler.suffix = '%Y-%m-%d'

root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)
root_logger.addHandler(error_handler)

logger = logging.getLogger(__name__)


def create_application() -> FastAPI:
    """Create and configure FastAPI application."""
    
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc"
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SESSION_SECRET_KEY,
        session_cookie="eido_session",
        same_site="lax",
        https_only=False,
    )
    
    # 添加请求日志中间件
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """记录所有HTTP请求"""
        start_time = time.time()
        
        # 记录请求
        logger.info(f"→ {request.method} {request.url.path}")
        
        # 处理请求
        response = await call_next(request)
        
        # 计算处理时间
        process_time = time.time() - start_time
        
        # 记录响应
        logger.info(
            f"← {request.method} {request.url.path} "
            f"Status: {response.status_code} "
            f"Duration: {process_time:.3f}s"
        )
        
        return response
    
    # Include API router
    app.include_router(api_router, prefix=settings.API_V1_STR)
    
    # Legacy route for backward compatibility
    @app.post("/api/chat")
    async def legacy_chat_endpoint(raw_request: Request):
        """Legacy chat endpoint for backward compatibility."""
        from app.api.v1.endpoints.chat import chat_completion
        from app.schemas.chat import ChatRequest
        from app.core.auth import get_current_user_id

        body = await raw_request.json()
        chat_request = ChatRequest(**body)
        user_id = get_current_user_id(raw_request)
        return await chat_completion(chat_request, user_id=user_id)
    
    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "message": f"Welcome to {settings.PROJECT_NAME}",
            "version": settings.VERSION,
            "docs": f"{settings.API_V1_STR}/docs"
        }
    
    @app.get("/health")
    async def health():
        """Health check endpoint."""
        return {"status": "healthy", "version": settings.VERSION}
    
    @app.on_event("startup")
    async def startup_event():
        """应用启动事件：根据运行模式初始化对应组件。

        三种角色：
        - user-runtime（EIDO_TRUST_GATEWAY=1）：仅初始化技能服务、会话存储与工作区
        - gateway（EIDO_SANDBOX_MODE=docker）：初始化 sandbox manager + 调度器（gateway 自身负责触发），
          技能服务用于跨用户共享只读
        - 单租户/local：保留原有完整初始化
        """
        from pathlib import Path
        from app.services.claude_skill_service import init_claude_skill_service
        from app.services.skill_management_service import init_skill_management_service
        from app.services.scheduled_task_store import ScheduledTaskStore
        from app.services.chat_session_store import init_chat_session_store
        from app.services.session_workspace import get_session_workspace_manager
        from app.services import scheduler_service
        from app.api.v1.endpoints import tasks as tasks_ep

        is_user_runtime = bool(settings.EIDO_TRUST_GATEWAY)
        is_gateway = (settings.EIDO_SANDBOX_MODE or "").lower() == "docker" and not is_user_runtime

        logger.info("=" * 60)
        if is_user_runtime:
            logger.info(f"启动为 USER 沙箱容器 user_id={settings.EIDO_USER_ID}")
        elif is_gateway:
            logger.info("启动为 GATEWAY 进程（EIDO_SANDBOX_MODE=docker）")
        else:
            logger.info("启动为单租户/兼容模式（EIDO_SANDBOX_MODE=local）")
        logger.info("=" * 60)

        # ---------- 技能服务（user / gateway / local 都需要）---------- #
        try:
            skills_dir = Path(settings.SKILLS_DIR)
            workspace_root = Path(settings.WORKSPACE_ROOT)
            # gateway / local 角色负责数据迁移；user 容器内技能目录是只读的
            if not is_user_runtime:
                _migrate_legacy_skills(skills_dir)
            svc = init_claude_skill_service(skills_dir, workspace_root)
            init_skill_management_service(skills_dir, workspace_root, svc)
            skill_count = len(svc.scan_skills())
            logger.info(f"✓ 技能服务初始化完成: 发现 {skill_count} 个 system 技能")
        except Exception as e:
            logger.error(f"✗ 技能服务初始化失败: {e}", exc_info=True)

        # ---------- OpenHarness 服务（仅 AGENT_HARNESS=open_harness 时初始化）---------- #
        harness_type = settings.AGENT_HARNESS.strip().lower()
        if harness_type == "open_harness":
            try:
                from app.services.open_harness_service import init_open_harness_service
                init_open_harness_service(
                    Path(settings.SKILLS_DIR), Path(settings.WORKSPACE_ROOT)
                )
                logger.info("✓ OpenHarnessService 初始化完成")
            except Exception as e:
                logger.error(f"✗ OpenHarnessService 初始化失败: {e}", exc_info=True)

        # ---------- 会话工作区 / 会话存储（user 与 local 需要；gateway 不需要）---------- #
        if not is_gateway:
            try:
                ws = get_session_workspace_manager()
                logger.info(f"✓ 会话工作区根目录: {ws.root}")
            except Exception as e:
                logger.error(f"✗ 会话工作区初始化失败: {e}", exc_info=True)

            try:
                init_chat_session_store()
                logger.info("✓ 会话存储 (ChatSessionStore) 初始化完成")
            except Exception as e:
                logger.error(f"✗ 会话存储初始化失败: {e}", exc_info=True)

        # ---------- 定时任务调度（gateway 与 local 需要；user 容器不跑调度）---------- #
        if not is_user_runtime:
            try:
                store = ScheduledTaskStore()
                store.connect()
                tasks_ep.set_store(store)
                scheduler_service.init_scheduler(store)
                logger.info("✓ 定时任务调度器初始化完成")
            except Exception as e:
                logger.error(f"✗ 定时任务调度器初始化失败: {e}", exc_info=True)

        # ---------- gateway 专属：sandbox 编排 ---------- #
        if is_gateway:
            try:
                from app.gateway.sandbox_manager import init_sandbox_manager
                mgr = init_sandbox_manager(mode=settings.EIDO_SANDBOX_MODE)
                await mgr.start_idle_gc()
                logger.info(f"✓ SandboxManager 初始化完成 mode={mgr.mode}")
            except Exception as e:
                logger.error(f"✗ SandboxManager 初始化失败: {e}", exc_info=True)

    @app.on_event("shutdown")
    async def shutdown_event():
        from app.services import scheduler_service
        scheduler_service.shutdown_scheduler()
        logger.info("Scheduler stopped")

        # gateway 关停 sandbox idle gc + httpx client
        if (settings.EIDO_SANDBOX_MODE or "").lower() == "docker" and not settings.EIDO_TRUST_GATEWAY:
            try:
                from app.gateway.sandbox_manager import get_sandbox_manager
                mgr = get_sandbox_manager()
                await mgr.stop_idle_gc()
                mgr.close()
            except Exception:
                pass
            try:
                from app.gateway.proxy import close_proxy_client
                await close_proxy_client()
            except Exception:
                pass

    logger.info(f"Application {settings.PROJECT_NAME} v{settings.VERSION} initialized")
    
    return app


app = create_application()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.LOG_LEVEL.lower()
    )

