#!/bin/bash

# Start Celery worker
echo "Starting Celery worker..."
celery -A celery_worker worker --loglevel=info --concurrency=2 &

# Start Celery Beat scheduler
echo "Starting Celery Beat..."
celery -A celery_worker beat --loglevel=info &


echo "Celery worker, Beat, and Flower are running in the background."