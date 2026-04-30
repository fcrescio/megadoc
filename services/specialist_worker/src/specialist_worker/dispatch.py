from celery import Celery

from common.config import get_settings

settings = get_settings()

dispatch_app = Celery(
    "specialist_dispatcher",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)


def dispatch_specialist_job(job_id: str, specialist_type: str) -> str:
    queue = _queue_for_specialist_type(specialist_type)
    result = dispatch_app.send_task(
        "specialist_worker.tasks.process_specialist_job",
        args=[job_id],
        queue=queue,
    )
    return result.id


def _queue_for_specialist_type(specialist_type: str) -> str:
    if specialist_type == "utility_bill":
        return settings.specialist_queue_utility
    if specialist_type == "accounting_statement":
        return settings.specialist_queue_accounting
    return settings.specialist_queue_utility
