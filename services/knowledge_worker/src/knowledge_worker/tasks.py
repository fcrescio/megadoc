"""Celery tasks for knowledge processing."""

import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import select, text
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from common.application.knowledge import has_active_ingestion_jobs
from common.application.specialists import ensure_specialist_jobs_for_scan_unit
from common.db.models import KnowledgeJob
from common.db.schema import ensure_knowledge_schema
from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.mock import MockDeterministicProvider
from knowledge_classifier.llm.openai_compat import OpenAICompatibleProvider
from knowledge_classifier.services.pipeline import KnowledgePipelineService
from specialist_worker.dispatch import dispatch_specialist_job

logger = logging.getLogger(__name__)

_schema_ready = False
_schema_ready_lock = threading.Lock()
_SCHEMA_ADVISORY_LOCK_ID = 713915042


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_schema_once(engine) -> None:
    global _schema_ready
    if _schema_ready:
        return
    with _schema_ready_lock:
        if _schema_ready:
            return
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": _SCHEMA_ADVISORY_LOCK_ID})
            try:
                ensure_knowledge_schema(engine)
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": _SCHEMA_ADVISORY_LOCK_ID})
                conn.commit()
        _schema_ready = True


def _advisory_lock_key(value: str) -> int:
    return uuid.UUID(value).int % 2_147_483_647


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
    _ensure_schema_once(engine)

    with Session(engine) as gate_session:
        if has_active_ingestion_jobs(gate_session):
            logger.info("knowledge_deferred_until_ocr_drain", extra={"scan_unit_id": scan_unit_id})
            latest_job = _get_latest_knowledge_job(gate_session, scan_unit_id, job_type="full_processing")
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

            with Session(engine) as specialist_session:
                specialist_jobs = ensure_specialist_jobs_for_scan_unit(specialist_session, scan_unit_id)
                specialist_session.flush()
                specialist_dispatches = [
                    (str(specialist_job.id), specialist_job.specialist_type)
                    for specialist_job in specialist_jobs
                ]
                specialist_session.commit()

            for specialist_job_id, specialist_type in specialist_dispatches:
                dispatch_specialist_job(specialist_job_id, specialist_type)

            _ensure_topic_finalization_job(engine, scan_unit_id)
            finalize_scan_topics_task.apply_async(args=[scan_unit_id], countdown=5, queue=settings.celery_queue)

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


@shared_task(bind=True, max_retries=30)
def finalize_scan_topics_task(self, scan_unit_id: str):
    """Assign topics after specialist jobs for a scan have completed."""
    logger.info("Task started: finalize_scan_topics %s", scan_unit_id)

    settings = get_settings()
    engine = create_engine(
        os.getenv("DATABASE_URL", "postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc"),
        echo=False,
    )
    _ensure_schema_once(engine)

    with Session(engine) as session:
        try:
            locked = session.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": _advisory_lock_key(scan_unit_id)},
            ).scalar_one()
            if not locked:
                logger.info("Topic finalization already active for scan_unit %s", scan_unit_id)
                return {"scan_unit_id": scan_unit_id, "status": "already_active"}

            finalization_job = _get_latest_knowledge_job(session, scan_unit_id, job_type="topic_finalization")
            if finalization_job is not None and finalization_job.status == "succeeded":
                logger.info("Topic finalization already completed for scan_unit %s", scan_unit_id)
                return {"scan_unit_id": scan_unit_id, "status": "already_finalized"}
            if finalization_job is None:
                finalization_job = KnowledgeJob(
                    scan_unit_id=uuid.UUID(scan_unit_id),
                    job_type="topic_finalization",
                    status="processing",
                    started_at=_utcnow(),
                    attempt_count=1,
                )
                session.add(finalization_job)
            else:
                finalization_job.status = "processing"
                finalization_job.started_at = _utcnow()
                finalization_job.finished_at = None
                finalization_job.error_message = None
                finalization_job.attempt_count += 1
            session.commit()

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

            pipeline = KnowledgePipelineService(llm_provider, session)
            result = pipeline.finalize_scan_topics(scan_unit_id)
            finalization_job.status = "succeeded"
            finalization_job.finished_at = _utcnow()
            finalization_job.error_message = None
            session.commit()
            logger.info("Task completed: %s", result)
            return result
        except RuntimeError as exc:
            session.rollback()
            with Session(engine) as status_session:
                finalization_job = _get_latest_knowledge_job(status_session, scan_unit_id, job_type="topic_finalization")
                if finalization_job is not None:
                    finalization_job.status = "pending"
                    finalization_job.error_message = str(exc)
                    status_session.commit()
            logger.info("Topic finalization deferred for scan_unit %s: %s", scan_unit_id, exc)
            rescheduled = finalize_scan_topics_task.apply_async(
                args=[scan_unit_id],
                countdown=15,
                queue=settings.celery_queue,
            )
            return {
                "scan_unit_id": scan_unit_id,
                "status": "deferred",
                "next_task_id": rescheduled.id,
            }
        except Exception as exc:
            session.rollback()
            with Session(engine) as status_session:
                finalization_job = _get_latest_knowledge_job(status_session, scan_unit_id, job_type="topic_finalization")
                if finalization_job is not None:
                    finalization_job.status = "failed"
                    finalization_job.finished_at = _utcnow()
                    finalization_job.error_message = str(exc)
                    status_session.commit()
            logger.error("Topic finalization failed: %s", exc, exc_info=True)
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
        finally:
            try:
                session.execute(
                    text("SELECT pg_advisory_unlock(:lock_id)"),
                    {"lock_id": _advisory_lock_key(scan_unit_id)},
                )
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()


def _get_latest_knowledge_job(session: Session, scan_unit_id: str, job_type: str | None = None) -> KnowledgeJob | None:
    if isinstance(scan_unit_id, str):
        scan_unit_id = uuid.UUID(scan_unit_id)
    query = (
        select(KnowledgeJob)
        .where(KnowledgeJob.scan_unit_id == scan_unit_id)
        .order_by(KnowledgeJob.created_at.desc())
    )
    if job_type is not None:
        query = query.where(KnowledgeJob.job_type == job_type)
    return session.execute(query.limit(1)).scalars().first()


def _ensure_topic_finalization_job(engine, scan_unit_id: str) -> None:
    with Session(engine) as session:
        existing = _get_latest_knowledge_job(session, scan_unit_id, job_type="topic_finalization")
        if existing is not None and existing.status in {"queued", "pending", "processing", "succeeded"}:
            return
        session.add(
            KnowledgeJob(
                scan_unit_id=uuid.UUID(scan_unit_id),
                job_type="topic_finalization",
                status="queued",
            )
        )
        session.commit()


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
        knowledge_job = _get_latest_knowledge_job(status_session, scan_unit_id, job_type="full_processing")
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
