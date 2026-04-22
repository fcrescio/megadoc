"""Celery app configuration for knowledge worker."""

import os

from celery import Celery

# Get config from environment
broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

celery_app = Celery(
    "knowledge_worker",
    broker=broker_url,
    backend=result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_routes={
        "knowledge_worker.tasks.*": {"queue": "knowledge"},
    },
)

# Auto-discover tasks
celery_app.autodiscover_tasks(["knowledge_worker.tasks"])
