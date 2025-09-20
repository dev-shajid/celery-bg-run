# celery_worker.py
import asyncio
import os
from kombu import Queue
from functools import lru_cache
from celery import Celery
from celery.utils.log import get_task_logger
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv

from gemini import run_search 
from cua import run_cua 

load_dotenv()

# ----------------- Settings -----------------
class CelerySettings(BaseSettings):
    CELERY_BROKER_URL: str = Field(..., env="CELERY_BROKER_URL")
    WORKER_CONCURRENCY: int = Field(4, env="CELERY_WORKER_CONCURRENCY")

    class Config:
        extra = "allow"


@lru_cache()
def get_celery_settings():
    return CelerySettings()


settings = get_celery_settings()
logger = get_task_logger(__name__)

# ----------------- Celery app -----------------
app = Celery("agent", broker=settings.CELERY_BROKER_URL)

AGENT_QUEUE = "agent_queue"

app.conf.task_queues = (Queue(AGENT_QUEUE),)
app.conf.task_routes = {
    "enqueue_pending_task": {"queue": AGENT_QUEUE},
    "run_agent_task": {"queue": AGENT_QUEUE},
    "check_pending_queues": {"queue": AGENT_QUEUE},
}

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    worker_concurrency=settings.WORKER_CONCURRENCY,
    broker_connection_retry_on_startup=True,
)

# ----------------- In-memory user queues & locks -----------------
# WARNING: In-memory locks work per worker process. Multi-node requires distributed lock.
USER_PENDING_TASKS = {}  # user_id -> list of task_data
USER_RUNNING = {}  # user_id -> bool


def is_user_running(user_id: int) -> bool:
    return USER_RUNNING.get(user_id, False)


def set_user_running(user_id: int) -> None:
    USER_RUNNING[user_id] = True


def clear_user_running(user_id: int) -> None:
    USER_RUNNING[user_id] = False


def add_pending_task(user_id: int, task_data: str) -> None:
    if user_id not in USER_PENDING_TASKS:
        USER_PENDING_TASKS[user_id] = []
    USER_PENDING_TASKS[user_id].append(task_data)


def pop_pending_task(user_id: int) -> str | None:
    tasks = USER_PENDING_TASKS.get(user_id)
    if not tasks:
        return None
    task = tasks.pop(0)
    if not tasks:
        USER_PENDING_TASKS.pop(user_id)
    return task


# ----------------- Celery tasks -----------------
@app.task(name="enqueue_pending_task")
def enqueue_pending_task(user_id: int, task_data: str):
    """
    Enqueue a user task into the in-memory queue.
    """
    add_pending_task(user_id, task_data)
    logger.info(f"📝 [ENQUEUE] User={user_id} Task={task_data}")
    return "queued"


@app.task(bind=True, max_retries=3, name="run_agent_task")
def run_agent_task(self, user_id: int, task_data: str):
    """
    Executes the async run_search function for a user.
    Ensures only one task per user runs at a time on this worker.
    """
    if is_user_running(user_id):
        # Already running: should not happen if scheduler is correct
        logger.warning(f"⏳ [SKIP] User={user_id} task skipped, already running. Re-enqueueing...")
        enqueue_pending_task.apply_async(args=[user_id, task_data])
        return "requeued"

    try:
        set_user_running(user_id)
        logger.info(f"🚀 [RUN] User={user_id} starting task: {task_data}")
        asyncio.run(run_cua())
        logger.info(f"✅ [DONE] User={user_id} completed task: {task_data}")
        return "done"

    except Exception as e:
        logger.error(f"❌ [RUN-ERR] User={user_id} error: {e}")
        raise self.retry(exc=e, countdown=60)

    finally:
        clear_user_running(user_id)


@app.task(name="check_pending_queues")
def check_pending_queues():
    """
    Scheduler task: checks all users and runs their next pending task if not running.
    """
    logger.info("🕒 [SCHEDULER] Checking pending queues...")
    for user_id in list(USER_PENDING_TASKS.keys()):
        if not is_user_running(user_id):
            next_task = pop_pending_task(user_id)
            if next_task:
                logger.info(f"➡️ [DISPATCH] User={user_id} -> running next task: {next_task}")
                run_agent_task.apply_async(args=[user_id, next_task], queue=AGENT_QUEUE)
    logger.info("📊 [SCHEDULER] Check complete.")
    return "ok"


# ----------------- Beat schedule -----------------
app.conf.beat_schedule = {
    "check-pending-queues-every-minute": {
        "task": "check_pending_queues",
        "schedule": 60.0,
    },
}
