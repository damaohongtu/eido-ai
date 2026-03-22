"""
Main FastAPI application entrypoint.
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.v1.api import api_router
import logging
import time
from pathlib import Path

# Configure logging with enhanced format
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)

# 创建日志格式器
detailed_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# 配置根日志记录器
root_logger = logging.getLogger()
root_logger.setLevel(settings.LOG_LEVEL)

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(settings.LOG_LEVEL)
console_handler.setFormatter(detailed_formatter)

# 文件处理器 - 所有日志
file_handler = logging.FileHandler(log_dir / 'app.log', encoding='utf-8')
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(detailed_formatter)

# 文件处理器 - 错误日志
error_handler = logging.FileHandler(log_dir / 'error.log', encoding='utf-8')
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(detailed_formatter)

# 添加处理器
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
    
    # Configure CORS（前端未使用 credentials，可安全使用 allow_origins=["*"]）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
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
    async def legacy_chat_endpoint(request: dict):
        """Legacy chat endpoint for backward compatibility."""
        from app.api.v1.endpoints.chat import chat_completion
        from app.schemas.chat import ChatRequest
        
        chat_request = ChatRequest(**request)
        return await chat_completion(chat_request)
    
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
        """应用启动事件：初始化技能服务"""
        from pathlib import Path
        from app.services.claude_skill_service import init_claude_skill_service

        logger.info("=" * 60)
        logger.info("正在初始化系统服务...")
        logger.info("=" * 60)

        try:
            skills_dir = Path(settings.SKILLS_DIR)
            workspace_root = Path(settings.WORKSPACE_ROOT)
            svc = init_claude_skill_service(skills_dir, workspace_root)
            skill_count = len(svc.scan_skills())
            logger.info(f"✓ 技能服务初始化完成: 发现 {skill_count} 个技能")
        except Exception as e:
            logger.error(f"✗ 技能服务初始化失败: {e}", exc_info=True)
    
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

