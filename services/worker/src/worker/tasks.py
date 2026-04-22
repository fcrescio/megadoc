from uuid import UUID

from celery.utils.log import get_task_logger

from common.application.services import JobService, OCRService
from common.db.session import SessionLocal
from common.domain.exceptions import ApplicationError
from worker.celery_app import celery_app

logger = get_task_logger(__name__)


@celery_app.task(name="worker.tasks.process_ingestion_job", bind=True, autoretry_for=(), retry_backoff=False)
def process_ingestion_job(self, job_id: str) -> dict[str, str]:
    session = SessionLocal()
    try:
        job_service = JobService(session)
        ocr_service = OCRService(session)
        job = job_service.jobs.get(UUID(job_id))
        if job is None:
            raise ApplicationError(f"Job {job_id} does not exist.")
        job_service.mark_running(job)
        logger.info("job_started", extra={"job_id": job_id, "document_id": str(job.document_id)})
        result = ocr_service.process_job(UUID(job_id))
        job_service.mark_succeeded(job)
        logger.info("job_succeeded", extra={"job_id": job_id, "ocr_result_id": str(result.id)})
        return {"job_id": job_id, "ocr_result_id": str(result.id)}
    except Exception as exc:
        session.rollback()
        job = JobService(session).jobs.get(UUID(job_id))
        if job is not None:
            JobService(session).mark_failed(job, str(exc))
        logger.exception("job_failed", extra={"job_id": job_id})
        raise
    finally:
        session.close()

