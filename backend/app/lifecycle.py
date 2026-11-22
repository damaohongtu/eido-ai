"""Start and stop the components owned by each deployment role."""

import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from pathlib import Path

from app.core.config import settings
from app.services.chat.session_store import ChatSessionStore, init_chat_session_store
from app.services.chat.session_workspace import get_session_workspace_manager
from app.services.claude.runtime import init_claude_runtime
from app.services.mcp.config_store import close_mcp_config_store
from app.services.projects.workspace import (
    get_project_workspace_manager,
    retry_pending_storage_cleanup,
)
from app.services.skills.catalog import migrate_legacy_skills
from app.services.skills.management import init_skill_management_service
from app.services.tasks import scheduler
from app.services.tasks.store import init_scheduled_task_store

logger = logging.getLogger(__name__)


async def _project_cleanup_loop(store: ChatSessionStore) -> None:
    while True:
        await asyncio.sleep(300)
        reconciliation = asyncio.create_task(
            asyncio.to_thread(retry_pending_storage_cleanup, store, reconcile_orphans=False)
        )
        try:
            result = await asyncio.shield(reconciliation)
            if result["completed"] or result["failed"]:
                logger.info("项目存储周期清理: %s", result)
        except asyncio.CancelledError:
            await asyncio.gather(reconciliation, return_exceptions=True)
            raise
        except Exception:
            logger.exception("项目存储周期清理异常")


async def _cancel(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@asynccontextmanager
async def application_lifespan(_app):
    is_gateway = settings.is_gateway_role
    is_sandbox = settings.EIDO_TRUST_GATEWAY
    role = "user" if is_sandbox else "gateway" if is_gateway else "local"
    logger.info("启动 Eido role=%s", role)

    async with AsyncExitStack() as cleanup:
        if not is_gateway:
            logger.info("会话工作区根目录: %s", get_session_workspace_manager().root)
            logger.info("项目资料根目录: %s", get_project_workspace_manager().root)
            chat_store = init_chat_session_store()
            cleanup.callback(chat_store.close)
            result = retry_pending_storage_cleanup(chat_store)
            if any(result.values()):
                logger.info("项目存储对账: %s", result)
            cleanup.push_async_callback(
                _cancel, asyncio.create_task(_project_cleanup_loop(chat_store))
            )

        skills_dir = Path(settings.SKILLS_DIR)
        if not is_sandbox:
            migrate_legacy_skills(skills_dir)
        runtime = init_claude_runtime(skills_dir, Path(settings.WORKSPACE_ROOT))
        cleanup.callback(close_mcp_config_store)
        cleanup.push_async_callback(runtime.shutdown)
        init_skill_management_service(runtime.catalog)
        logger.info("技能目录初始化完成: %d 个系统技能", len(runtime.catalog.scan_skills()))

        if is_gateway:
            from app.gateway.proxy import close_proxy_client
            from app.gateway.sandbox_manager import init_sandbox_manager

            manager = init_sandbox_manager(mode=settings.EIDO_SANDBOX_MODE)
            cleanup.push_async_callback(close_proxy_client)
            cleanup.callback(manager.close)
            cleanup.push_async_callback(manager.stop_idle_gc)
            await manager.start_idle_gc()

        if not is_sandbox:
            try:
                store = init_scheduled_task_store()
                cleanup.callback(scheduler.shutdown_scheduler)
                scheduler.init_scheduler(store)
            except Exception:
                logger.exception("定时任务调度器初始化失败")
        yield
