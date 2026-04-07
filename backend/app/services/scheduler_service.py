"""
APScheduler wrapper: loads tasks from SQLite, manages job lifecycle.
"""
import asyncio
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.services.scheduled_task_store import ScheduledTaskStore

logger = logging.getLogger(__name__)

_store: ScheduledTaskStore | None = None
_scheduler: BackgroundScheduler | None = None


def _parse_trigger(schedule: str):
    """Parse schedule string into an APScheduler trigger."""
    s = schedule.strip()
    if s.startswith("interval:"):
        seconds = int(s.split(":", 1)[1])
        return IntervalTrigger(seconds=seconds)
    return CronTrigger.from_crontab(s)


def _run_task_job(task_id: str):
    """Job function called by APScheduler (runs in thread pool)."""
    from app.services.task_executor import execute_task

    if _store is None:
        logger.error("Store not available")
        return

    task = _store.get_by_id(task_id)
    if not task or not task["enabled"]:
        logger.warning(f"Task {task_id} not found or disabled, skipping")
        return

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(execute_task(task))
    finally:
        loop.close()

    _store.update_last_run(task_id)


def add_job(task: dict):
    if _scheduler is None:
        return
    try:
        trigger = _parse_trigger(task["schedule"])
        _scheduler.add_job(
            _run_task_job,
            trigger=trigger,
            args=[task["id"]],
            id=task["id"],
            replace_existing=True,
        )
        logger.info(f"Scheduler: added job {task['id']} schedule={task['schedule']}")
    except Exception:
        logger.exception(f"Scheduler: failed to add job {task['id']}")


def remove_job(task_id: str):
    if _scheduler is None:
        return
    try:
        _scheduler.remove_job(task_id)
        logger.info(f"Scheduler: removed job {task_id}")
    except Exception:
        logger.debug(f"Scheduler: job {task_id} not found for removal")


def init_scheduler(store: ScheduledTaskStore):
    global _store, _scheduler
    _store = store
    _scheduler = BackgroundScheduler()

    tasks = store.list_all_enabled()
    for t in tasks:
        add_job(t)

    _scheduler.start()
    logger.info(f"Scheduler started with {len(tasks)} jobs")


def shutdown_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
        _scheduler = None
