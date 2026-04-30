from celery import Celery

from common.config import get_settings

settings = get_settings()

celery_app = Celery(
    "specialist_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["specialist_worker.tasks"],
)

celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
)
