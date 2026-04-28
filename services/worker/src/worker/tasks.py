import os
from uuid import UUID

from celery import Celery
from celery.utils.log import get_task_logger

from common.application.knowledge import (
    ensure_scan_unit_for_ocr_result,
    get_dispatchable_knowledge_scan_unit_ids,
    has_active_ingestion_jobs,
    mark_knowledge_job_pending_dispatch,
)
from common.application.services import JobService, OCRService
from common.db.session import SessionLocal
from common.domain.exceptions import ApplicationError
from worker.celery_app import celery_app

logger = get_task_logger(__name__)

knowledge_dispatch_app = Celery(
    "worker_to_knowledge_dispatch",
    broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1"),
)


def _dispatch_knowledge_scan_units(session, scan_unit_ids: list[UUID]) -> int:
    dispatched_ids: list[str] = []
    for scan_unit_id in scan_unit_ids:
        if mark_knowledge_job_pending_dispatch(session, scan_unit_id):
            dispatched_ids.append(str(scan_unit_id))
    if not dispatched_ids:
        session.rollback()
        return 0
    session.commit()
    for scan_unit_id in dispatched_ids:
        knowledge_dispatch_app.send_task(
            "knowledge_worker.tasks.process_scan_unit_task",
            args=[scan_unit_id],
            queue="knowledge",
        )
    return len(dispatched_ids)


@celery_app.task(name="worker.tasks.process_ingestion_job", bind=True, autoretry_for=(), retry_backoff=False)
def process_ingestion_job(self, job_id: str, backend_override: str | None = None) -> dict[str, str]:
    session = SessionLocal()
    try:
        job_service = JobService(session)
        ocr_service = OCRService(
            session,
            settings=ocr_service_settings(backend_override),
        )
        job = job_service.jobs.get(UUID(job_id))
        if job is None:
            raise ApplicationError(f"Job {job_id} does not exist.")
        job_service.mark_running(job)
        logger.info(
            "job_started",
            extra={
                "job_id": job_id,
                "document_id": str(job.document_id),
                "ocr_backend": backend_override or ocr_service.settings.ocr_backend,
            },
        )
        result = ocr_service.process_job(UUID(job_id))
        job_service.mark_succeeded(job)
        scan_unit, _, _, should_dispatch = ensure_scan_unit_for_ocr_result(session, result)
        session.commit()
        if not has_active_ingestion_jobs(session):
            dispatchable_ids = get_dispatchable_knowledge_scan_unit_ids(session)
            if should_dispatch and scan_unit.id not in dispatchable_ids:
                dispatchable_ids.append(scan_unit.id)
            dispatched_count = _dispatch_knowledge_scan_units(session, dispatchable_ids)
            if dispatched_count:
                logger.info(
                    "knowledge_released_after_ocr_drain",
                    extra={"job_id": job_id, "dispatched_count": dispatched_count},
                )
        logger.info("job_succeeded", extra={"job_id": job_id, "ocr_result_id": str(result.id)})
        return {"job_id": job_id, "ocr_result_id": str(result.id)}
    except Exception as exc:
        session.rollback()
        job = JobService(session).jobs.get(UUID(job_id))
        if job is not None:
            JobService(session).mark_failed(job, str(exc))
            if not has_active_ingestion_jobs(session):
                dispatchable_ids = get_dispatchable_knowledge_scan_unit_ids(session)
                dispatched_count = _dispatch_knowledge_scan_units(session, dispatchable_ids)
                if dispatched_count:
                    logger.info(
                        "knowledge_released_after_ocr_failure_drain",
                        extra={"job_id": job_id, "dispatched_count": dispatched_count},
                    )
        logger.exception("job_failed", extra={"job_id": job_id})
        raise
    finally:
        session.close()


def ocr_service_settings(backend_override: str | None):
    from common.config import get_settings

    settings = get_settings()
    if not backend_override:
        return settings
    return settings.model_copy(update={"ocr_backend": backend_override})
