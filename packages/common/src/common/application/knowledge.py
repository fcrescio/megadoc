from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import KnowledgeJob, OCRResult, ScanUnit


def ensure_scan_unit_for_ocr_result(
    session: Session,
    ocr_result: OCRResult,
) -> tuple[ScanUnit, KnowledgeJob, bool, bool]:
    existing_scan_unit = session.execute(
        select(ScanUnit).where(ScanUnit.source_ocr_result_id == ocr_result.id)
    ).scalar_one_or_none()

    if existing_scan_unit is None:
        scan_unit = ScanUnit(
            source_document_id=ocr_result.document_id,
            source_document_version_id=ocr_result.document_version_id,
            source_ocr_result_id=ocr_result.id,
            page_count=ocr_result.page_count,
            status="pending",
        )
        session.add(scan_unit)
        session.flush()
        created_scan_unit = True
    else:
        scan_unit = existing_scan_unit
        created_scan_unit = False

    knowledge_job = session.execute(
        select(KnowledgeJob)
        .where(KnowledgeJob.scan_unit_id == scan_unit.id)
        .order_by(KnowledgeJob.created_at.desc())
    ).scalar_one_or_none()

    should_dispatch = False
    if knowledge_job is None:
        knowledge_job = KnowledgeJob(
            scan_unit_id=scan_unit.id,
            job_type="full_processing",
            status="queued",
        )
        session.add(knowledge_job)
        session.flush()
        should_dispatch = True
    elif knowledge_job.status in {"failed", "completed"}:
        knowledge_job = KnowledgeJob(
            scan_unit_id=scan_unit.id,
            job_type="full_processing",
            status="queued",
        )
        session.add(knowledge_job)
        session.flush()
        should_dispatch = True
    elif knowledge_job.status == "succeeded":
        should_dispatch = False
    elif knowledge_job.status == "pending":
        knowledge_job.status = "queued"
        should_dispatch = True

    return scan_unit, knowledge_job, created_scan_unit, should_dispatch


def parse_uuid(value: str | uuid.UUID) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)
