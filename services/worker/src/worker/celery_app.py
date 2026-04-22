from celery import Celery

from common.config import get_settings

settings = get_settings()

celery_app = Celery(
    "megadoc-worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["worker.tasks"],
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    task_routes={"worker.tasks.process_ingestion_job": {"queue": "ingestion"}},
)
