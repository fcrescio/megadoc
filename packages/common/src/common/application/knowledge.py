from __future__ import annotations

import uuid

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import (
    DocumentUnit,
    DocumentUnitTopicAssignment,
    IngestionJob,
    KnowledgeJob,
    OCRResult,
    ScanUnit,
    Topic,
)


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


def has_active_ingestion_jobs(session: Session) -> bool:
    active_count = session.execute(
        select(func.count())
        .select_from(IngestionJob)
        .where(
            IngestionJob.job_type == "ingest",
            IngestionJob.status.in_(("queued", "running")),
        )
    ).scalar_one()
    return bool(active_count)


def get_dispatchable_knowledge_scan_unit_ids(session: Session) -> list[uuid.UUID]:
    rows = session.execute(
        select(KnowledgeJob)
        .where(KnowledgeJob.status == "queued")
        .order_by(KnowledgeJob.created_at.desc())
    ).scalars().all()

    seen: set[uuid.UUID] = set()
    scan_unit_ids: list[uuid.UUID] = []
    for job in rows:
        if job.scan_unit_id in seen:
            continue
        seen.add(job.scan_unit_id)
        scan_unit_ids.append(job.scan_unit_id)
    scan_unit_ids.reverse()
    return scan_unit_ids


def mark_knowledge_job_pending_dispatch(session: Session, scan_unit_id: str | uuid.UUID) -> bool:
    parsed_scan_unit_id = parse_uuid(scan_unit_id)
    knowledge_job = session.execute(
        select(KnowledgeJob)
        .where(KnowledgeJob.scan_unit_id == parsed_scan_unit_id)
        .order_by(KnowledgeJob.created_at.desc())
    ).scalar_one_or_none()
    if knowledge_job is None:
        return False
    if knowledge_job.status != "queued":
        return False
    knowledge_job.status = "pending"
    session.flush()
    return True


def parse_uuid(value: str | uuid.UUID) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)


def upsert_document_unit_topic_assignment(
    session: Session,
    doc_unit: DocumentUnit,
    topic: Topic,
    assignment_role: str,
    confidence: float | None = None,
    rationale: str | None = None,
) -> DocumentUnitTopicAssignment:
    """Create or update a topic assignment for a document unit.

    Matches on (document_unit_id, topic_id, assignment_role).
    If an assignment already exists, updates confidence and rationale.
    Otherwise creates a new assignment.
    """
    existing = session.execute(
        select(DocumentUnitTopicAssignment).where(
            DocumentUnitTopicAssignment.document_unit_id == doc_unit.id,
            DocumentUnitTopicAssignment.topic_id == topic.id,
            DocumentUnitTopicAssignment.assignment_role == assignment_role,
        )
    ).scalar_one_or_none()

    if existing is not None:
        if confidence is not None:
            existing.confidence = confidence
        if rationale is not None:
            existing.rationale = rationale
        return existing

    assignment = DocumentUnitTopicAssignment(
        document_unit_id=doc_unit.id,
        topic_id=topic.id,
        assignment_role=assignment_role,
        confidence=confidence,
        rationale=rationale,
    )
    session.add(assignment)
    return assignment
