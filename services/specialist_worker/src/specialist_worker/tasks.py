from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from celery import shared_task
from common.application.graph import project_document_unit
from common.application.retry import retry_delay_seconds
from common.application.specialist_contracts import (
    SpecialistExecutionContext,
    attach_specialist_envelope,
)
from common.application.specialists import extract_document_unit_text
from common.db.models import (
    DocumentUnit,
    DocumentUnitLink,
    ScanUnit,
    SpecialistJob,
    SpecialistResult,
)
from common.db.schema import ensure_knowledge_schema
from knowledge_classifier.config import get_settings as get_knowledge_settings
from knowledge_classifier.llm.openai_compat import OpenAICompatibleProvider
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session, selectinload

from specialist_worker.registry import build_specialist_registry

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


@shared_task(bind=True, max_retries=2)
def process_specialist_job(self, specialist_job_id: str):
    logger.info("Task started: process_specialist_job %s", specialist_job_id)

    engine = create_engine(
        os.getenv("DATABASE_URL", "postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc"),
        echo=False,
    )
    _ensure_schema_once(engine)
    _update_specialist_job(engine, specialist_job_id, status="processing", started_at=_utcnow(), increment_attempt=True)

    with Session(engine) as session:
        try:
            specialist_job = _get_specialist_job(session, specialist_job_id)
            if specialist_job is None:
                raise ValueError("Specialist job not found.")

            document_unit = session.execute(
                select(DocumentUnit)
                .where(DocumentUnit.id == specialist_job.document_unit_id)
                .options(
                    selectinload(DocumentUnit.document_type),
                    selectinload(DocumentUnit.entities),
                    selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.ocr_result),
                    selectinload(DocumentUnit.specialist_results),
                )
            ).scalar_one()
            ocr_result = document_unit.scan_unit.ocr_result
            segment_text = extract_document_unit_text(document_unit, ocr_result)

            registry = build_specialist_registry(_accounting_reconciliation_provider)
            handler = registry.get(specialist_job.specialist_type)
            extraction = handler.extract(SpecialistExecutionContext(
                session=session,
                document_unit=document_unit,
                text=segment_text,
                structured_json=ocr_result.structured_json or {},
                input_version=specialist_job.input_version or "",
            ))
            validation = handler.validate(extraction)
            presentation = handler.present(extraction.payload)
            result_json = attach_specialist_envelope(
                extraction,
                handler=handler,
                validation=validation,
                presentation=presentation,
            )
            confidence = extraction.confidence
            schema_version = handler.schema_version
            review_status = (
                "auto_accepted"
                if validation.status == "valid" and confidence >= 0.7
                else "needs_review"
            )
            _replace_links(session, document_unit.id, specialist_job.specialist_type, extraction.links)

            existing_result = session.execute(
                select(SpecialistResult)
                .where(
                    SpecialistResult.document_unit_id == document_unit.id,
                    SpecialistResult.specialist_type == specialist_job.specialist_type,
                )
                .order_by(SpecialistResult.created_at.desc())
            ).scalar_one_or_none()
            if existing_result is None:
                specialist_result = SpecialistResult(
                    document_unit_id=document_unit.id,
                    specialist_type=specialist_job.specialist_type,
                    schema_version=schema_version,
                    confidence=confidence,
                    review_status=review_status,
                    result_json=result_json,
                )
                session.add(specialist_result)
            else:
                specialist_result = existing_result
                result_json = handler.reapply_corrections(result_json, specialist_result.result_json)
                specialist_result.schema_version = schema_version
                specialist_result.confidence = confidence
                specialist_result.review_status = review_status
                specialist_result.result_json = result_json
                specialist_result.updated_at = _utcnow()

            session.flush()
            projection_unit = session.execute(
                select(DocumentUnit)
                .where(DocumentUnit.id == document_unit.id)
                .options(
                    selectinload(DocumentUnit.document_type),
                    selectinload(DocumentUnit.entities),
                    selectinload(DocumentUnit.specialist_results),
                )
            ).scalar_one()
            project_document_unit(session, projection_unit)
            handler.project(session, projection_unit, specialist_result)
            session.commit()
            _update_specialist_job(engine, specialist_job_id, status="succeeded", finished_at=_utcnow(), error_message=None)
            return {"specialist_job_id": specialist_job_id, "status": "succeeded", "specialist_type": specialist_job.specialist_type}
        except Exception as exc:
            logger.error("Specialist task failed: %s", exc, exc_info=True)
            session.rollback()
            _update_specialist_job(engine, specialist_job_id, status="failed", finished_at=_utcnow(), error_message=str(exc))
            raise self.retry(
                exc=exc,
                countdown=retry_delay_seconds(self.request.retries, key=f"specialist:{specialist_job_id}"),
            )
        finally:
            session.close()


def _accounting_reconciliation_provider() -> OpenAICompatibleProvider | None:
    enabled = (
        os.getenv("SPECIALIST_ACCOUNTING_LLM_RECONCILIATION_ENABLED", "true").strip().lower()
    )
    if enabled not in {"1", "true", "yes", "on"}:
        return None
    settings = get_knowledge_settings()
    endpoint = os.getenv("KN_WORKER_LLM_ENDPOINT", settings.llm_endpoint)
    if endpoint.startswith("mock://"):
        return None
    timeout = int(os.getenv("SPECIALIST_ACCOUNTING_LLM_RECONCILIATION_TIMEOUT", "240"))
    max_tokens = int(os.getenv("SPECIALIST_ACCOUNTING_LLM_RECONCILIATION_MAX_TOKENS", "4096"))
    return OpenAICompatibleProvider(
        base_url=endpoint,
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        timeout=timeout,
        max_tokens=min(max_tokens, settings.llm_max_tokens),
    )


def _replace_links(
    session: Session,
    document_unit_id: uuid.UUID,
    specialist_type: str,
    links: list[DocumentUnitLink],
) -> None:
    session.execute(
        delete(DocumentUnitLink).where(
            DocumentUnitLink.source_document_unit_id == document_unit_id,
            DocumentUnitLink.link_type.startswith(f"{specialist_type}_"),
        )
    )
    for link in links:
        session.add(link)


def _get_specialist_job(session: Session, specialist_job_id: str | uuid.UUID) -> SpecialistJob | None:
    if isinstance(specialist_job_id, str):
        specialist_job_id = uuid.UUID(specialist_job_id)
    return session.execute(
        select(SpecialistJob).where(SpecialistJob.id == specialist_job_id)
    ).scalar_one_or_none()


def _update_specialist_job(
    engine,
    specialist_job_id: str,
    *,
    status: str,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    increment_attempt: bool = False,
    error_message: str | None = None,
) -> None:
    with Session(engine) as session:
        specialist_job = _get_specialist_job(session, specialist_job_id)
        if specialist_job is None:
            return
        specialist_job.status = status
        if started_at is not None:
            specialist_job.started_at = started_at
        if finished_at is not None:
            specialist_job.finished_at = finished_at
        if increment_attempt:
            specialist_job.attempt_count += 1
        specialist_job.error_message = error_message
        session.commit()
