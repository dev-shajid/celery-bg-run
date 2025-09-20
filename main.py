from fastapi import FastAPI
from celery_worker import enqueue_pending_task

app = FastAPI(title="Background Task API", version="1.0.0")

@app.get("/")
def root():
    return {"status": "ok"}

@app.post("/submit-task")
def submit_task(user_id: int, task: str):
    # Push to pending queue; scheduler will dispatch execution
    enqueue_pending_task.delay(user_id, task)
    return {"status": "queued"}