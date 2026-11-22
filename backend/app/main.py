"""
Main FastAPI application entrypoint.
"""

import logging
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.v1.api import api_router, legacy_chat_endpoint
from app.core.config import settings
from app.core.logging_context import (
    TRACE_ID_HEADER,
    configure_logging,
    reset_session_id,
    reset_trace_id,
    resolve_trace_id,
    set_session_id,
    set_trace_id,
)
from app.lifecycle import application_lifespan

configure_logging(settings.LOG_DIR, settings.LOG_LEVEL)

logger = logging.getLogger(__name__)


def create_application() -> FastAPI:
    """Create and configure FastAPI application."""

    app = FastAPI(
        title=settings.PROJECT_NAME,
        lifespan=application_lifespan,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_STR}/openapi.json",
        docs_url=f"{settings.API_V1_STR}/docs",
        redoc_url=f"{settings.API_V1_STR}/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.BACKEND_CORS_ORIGINS,
        allow_origin_regex=settings.BACKEND_CORS_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Session-Id"],
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
        trace_id = resolve_trace_id(request.headers.get(TRACE_ID_HEADER))
        trace_token = set_trace_id(trace_id)
        request.state.trace_id = trace_id
        try:
            logger.info("→ %s %s", request.method, request.url.path)
            response = await call_next(request)
            process_time = time.time() - start_time
            response.headers[TRACE_ID_HEADER] = trace_id
            response_session_token = set_session_id(getattr(request.state, "session_id", "-"))
            try:
                logger.info(
                    "← %s %s Status: %s Duration: %.3fs",
                    request.method,
                    request.url.path,
                    response.status_code,
                    process_time,
                )
            finally:
                reset_session_id(response_session_token)
            return response
        except Exception:
            process_time = time.time() - start_time
            error_session_token = set_session_id(getattr(request.state, "session_id", "-"))
            try:
                logger.exception(
                    "← %s %s Status: 500 Duration: %.3fs",
                    request.method,
                    request.url.path,
                    process_time,
                )
            finally:
                reset_session_id(error_session_token)
            raise
        finally:
            reset_trace_id(trace_token)

    # Include API router
    app.include_router(api_router, prefix=settings.API_V1_STR)

    app.add_api_route("/api/chat", legacy_chat_endpoint, methods=["POST"])

    @app.get("/")
    async def root():
        """Root endpoint."""
        return {
            "message": f"Welcome to {settings.PROJECT_NAME}",
            "version": settings.VERSION,
            "docs": f"{settings.API_V1_STR}/docs",
        }

    @app.get("/health")
    async def health():
        """Health check endpoint."""
        from app.services.chat.execution_guard import get_chat_execution_guard

        return {
            "status": "healthy",
            "version": settings.VERSION,
            "active_runs": get_chat_execution_guard().active_count(),
        }

    logger.info(f"Application {settings.PROJECT_NAME} v{settings.VERSION} initialized")

    return app


app = create_application()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app", host="0.0.0.0", port=8000, reload=True, log_level=settings.LOG_LEVEL.lower()
    )
