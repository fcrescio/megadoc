from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone

from celery import shared_task
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, selectinload

from common.application.accounting import project_accounting_result
from common.application.graph import project_document_unit
from common.application.specialists import extract_document_unit_text
from common.db.models import DocumentUnit, DocumentUnitLink, ScanUnit, SpecialistJob, SpecialistResult
from common.db.schema import ensure_knowledge_schema
from specialist_worker.services.accounting_statement import process_accounting_statement
from specialist_worker.services.utility_bill import process_utility_bill

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@shared_task(bind=True, max_retries=2)
def process_specialist_job(self, specialist_job_id: str):
    logger.info("Task started: process_specialist_job %s", specialist_job_id)

    engine = create_engine(
        os.getenv("DATABASE_URL", "postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc"),
        echo=False,
    )
    ensure_knowledge_schema(engine)
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

            if specialist_job.specialist_type == "utility_bill":
                result_json, links, confidence = process_utility_bill(
                    session,
                    document_unit,
                    segment_text,
                    specialist_job.input_version or "",
                )
                _replace_links(session, document_unit.id, "utility_bill_detail", links)
                schema_version = "utility_bill_v1"
            elif specialist_job.specialist_type == "accounting_statement":
                result_json, confidence = process_accounting_statement(
                    document_unit,
                    segment_text,
                    specialist_job.input_version or "",
                    structured_json=ocr_result.structured_json,
                )
                schema_version = "accounting_statement_v2"
            else:
                raise ValueError(f"Unsupported specialist type: {specialist_job.specialist_type}")

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
                    review_status="auto_accepted" if confidence >= 0.7 else "needs_review",
                    result_json=result_json,
                )
                session.add(specialist_result)
            else:
                specialist_result = existing_result
                specialist_result.schema_version = schema_version
                specialist_result.confidence = confidence
                specialist_result.review_status = "auto_accepted" if confidence >= 0.7 else "needs_review"
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
            if specialist_job.specialist_type == "accounting_statement":
                project_accounting_result(session, projection_unit, specialist_result)
            session.commit()
            _update_specialist_job(engine, specialist_job_id, status="succeeded", finished_at=_utcnow(), error_message=None)
            return {"specialist_job_id": specialist_job_id, "status": "succeeded", "specialist_type": specialist_job.specialist_type}
        except Exception as exc:
            logger.error("Specialist task failed: %s", exc, exc_info=True)
            session.rollback()
            _update_specialist_job(engine, specialist_job_id, status="failed", finished_at=_utcnow(), error_message=str(exc))
            raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))
        finally:
            session.close()


def _replace_links(
    session: Session,
    document_unit_id: uuid.UUID,
    link_type: str,
    links: list[DocumentUnitLink],
) -> None:
    session.execute(
        delete(DocumentUnitLink).where(
            DocumentUnitLink.source_document_unit_id == document_unit_id,
            DocumentUnitLink.link_type == link_type,
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
