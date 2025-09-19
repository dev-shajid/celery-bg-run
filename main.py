from fastapi import FastAPI
import redis
import json

app = FastAPI(title="Background Task API", version="1.0.0")

r = redis.Redis(host='redis', port=6379, db=1)

@app.get("/")
async def root():
    return {"message": "FastAPI Browser Automation Server is running"}

@app.post("/submit-task")
async def submit_task(user_id: int, task: str):
    r.rpush(f"user:{user_id}:pending", json.dumps({"task": task, "user_id": user_id}))
    return {"status": "queued"}