from celery import Celery
from gemini import run_search
import redis
import json

celery_app = Celery(
    "tasks",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)

r = redis.Redis(host='localhost', port=6379, db=1)

def get_running_task(user_id):
    return r.get(f"user:{user_id}:running")

def set_running_task(user_id, task_id):
    r.set(f"user:{user_id}:running", task_id)

def clear_running_task(user_id):
    r.delete(f"user:{user_id}:running")

def queue_pending_task(user_id, task):
    r.rpush(f"user:{user_id}:pending", json.dumps(task))

def pop_pending_task(user_id):
    next_task = r.lpop(f"user:{user_id}:pending")
    if next_task:
        return json.loads(next_task)
    return None

@celery_app.task(bind=True)
def run_agent_task(self, task: str, user_id: int):
    # Only start if no running task for user
    current_running = get_running_task(user_id)
    if current_running and current_running != self.request.id:
        # Already running, queue as pending
        queue_pending_task(user_id, {"task": task, "user_id": user_id})
        print(f"Queued task for user {user_id}: {self.request.id}")
        return "queued"
    # Mark as running
    set_running_task(user_id, self.request.id)
    import asyncio
    try:
        asyncio.run(run_search(task))
        print(f"🔥Task for user {user_id} completed.")
    except Exception as e:
        print(f"❌ Error for user {user_id}: {e}")
    # Clear running slot
    clear_running_task(user_id)
    # Start next pending task if available
    next_task = pop_pending_task(user_id)
    if next_task:
        print(f"Dispatching next pending task for user {user_id}")
        run_agent_task.delay(next_task['task'], user_id)
    return "done"


@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # Run every minute (adjust as needed)
    sender.add_periodic_task(60.0, check_pending_queues.s(), name='Check pending queues every minute')

@celery_app.task
def check_pending_queues():
    print('🕣[Scheduler]: Checking pending queues...')
    # Scan all user pending queues
    for key in r.scan_iter("user:*:pending"):
        user_id = int(key.decode().split(":")[1])
        current_running = get_running_task(user_id)
        if not current_running:
            next_task = pop_pending_task(user_id)
            if next_task:
                print(f"Periodic dispatch for user {user_id}")
                run_agent_task.delay(next_task['task'], user_id)