#!/bin/bash
set -euo pipefail

# Start worker
celery -A celery_worker worker \
  --loglevel=info \
  --concurrency=2 \
  --hostname=worker@%h \
  --without-gossip --without-mingle &
WORKER_PID=$!

# Start beat (no --hostname here)
celery -A celery_worker beat \
  --loglevel=info \
  --pidfile=celerybeat.pid \
  --schedule=celerybeat-schedule &
BEAT_PID=$!

# Forward signals so both stop cleanly
trap "echo 'Stopping...'; kill -TERM $WORKER_PID $BEAT_PID; wait $WORKER_PID $BEAT_PID" SIGINT SIGTERM

# Wait for both
wait $WORKER_PID $BEAT_PID
