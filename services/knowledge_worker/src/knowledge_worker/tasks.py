"""Celery tasks for knowledge processing."""

import logging
import os
import uuid
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from common.application.knowledge import has_active_ingestion_jobs
from common.db.models import KnowledgeJob
from common.db.schema import ensure_knowledge_schema
from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.mock import MockDeterministicProvider
from knowledge_classifier.llm.openai_compat import OpenAICompatibleProvider
from knowledge_classifier.services.pipeline import KnowledgePipelineService

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@shared_task(bind=True, max_retries=3)
def process_scan_unit_task(self, scan_unit_id: str):
    """Process a scan unit through the knowledge pipeline.
    
    Args:
        scan_unit_id: ID of the scan unit to process
    """
    logger.info(f"Task started: process_scan_unit {scan_unit_id}")
    
    settings = get_settings()
    
    # Create DB session
    engine = create_engine(
        os.getenv("DATABASE_URL", "postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc"),
        echo=False,
    )
    ensure_knowledge_schema(engine)

    with Session(engine) as gate_session:
        if has_active_ingestion_jobs(gate_session):
            logger.info("knowledge_deferred_until_ocr_drain", extra={"scan_unit_id": scan_unit_id})
            latest_job = _get_latest_knowledge_job(gate_session, scan_unit_id)
            if latest_job is not None:
                latest_job.status = "pending"
                gate_session.commit()
            self.apply_async(args=[scan_unit_id], countdown=180, queue=settings.celery_queue)
            return {"scan_unit_id": scan_unit_id, "status": "deferred_for_ocr_priority"}

    _update_knowledge_job(
        engine,
        scan_unit_id,
        status="processing",
        started_at=_utcnow(),
        increment_attempt=True,
        error_message=None,
    )
    
    with Session(engine) as session:
        try:
            # Initialize LLM provider
            if settings.use_mock_llm:
                llm_provider = MockDeterministicProvider(model=settings.llm_model)
            else:
                llm_provider = OpenAICompatibleProvider(
                    base_url=settings.llm_endpoint,
                    model=settings.llm_model,
                    api_key=settings.llm_api_key,
                    timeout=settings.llm_timeout,
                    max_tokens=settings.llm_max_tokens,
                )
            
            # Create pipeline service
            pipeline = KnowledgePipelineService(llm_provider, session)
            
            # Process scan unit (sync)
            result = pipeline.process_scan_unit(scan_unit_id)
            
            # Commit changes
            session.commit()
            _update_knowledge_job(
                engine,
                scan_unit_id,
                status="succeeded",
                finished_at=_utcnow(),
                error_message=None,
            )
            
            logger.info(f"Task completed: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Task failed: {e}", exc_info=True)
            session.rollback()
            _update_knowledge_job(
                engine,
                scan_unit_id,
                status="failed",
                finished_at=_utcnow(),
                error_message=str(e),
            )
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        finally:
            session.close()


def _get_latest_knowledge_job(session: Session, scan_unit_id: str) -> KnowledgeJob | None:
    if isinstance(scan_unit_id, str):
        scan_unit_id = uuid.UUID(scan_unit_id)
    return session.execute(
        select(KnowledgeJob)
        .where(KnowledgeJob.scan_unit_id == scan_unit_id)
        .order_by(KnowledgeJob.created_at.desc())
    ).scalar_one_or_none()


def _update_knowledge_job(
    engine,
    scan_unit_id: str,
    *,
    status: str,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    increment_attempt: bool = False,
    error_message: str | None = None,
) -> None:
    with Session(engine) as status_session:
        knowledge_job = _get_latest_knowledge_job(status_session, scan_unit_id)
        if knowledge_job is None:
            return
        knowledge_job.status = status
        if started_at is not None:
            knowledge_job.started_at = started_at
        if finished_at is not None:
            knowledge_job.finished_at = finished_at
        if increment_attempt:
            knowledge_job.attempt_count += 1
        knowledge_job.error_message = error_message
        status_session.commit()
