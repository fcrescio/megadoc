from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from common.db.models import DocumentUnit, OCRResult, ScanUnit, SpecialistJob, SpecialistResult


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def extract_document_unit_text(document_unit: DocumentUnit, ocr_result: OCRResult) -> str:
    markdown = ocr_result.markdown_text or ""
    if not markdown or ocr_result.page_count <= 0:
        return ""

    lines = markdown.split("\n")
    lines_per_page = max(1, len(lines) // max(1, ocr_result.page_count))
    start_idx = (document_unit.start_page - 1) * lines_per_page
    end_idx = document_unit.end_page * lines_per_page
    return "\n".join(lines[start_idx:end_idx]).strip()


def route_specialists_for_document_unit(document_unit: DocumentUnit, segment_text: str) -> list[str]:
    doc_type = document_unit.document_type.code if document_unit.document_type else None
    text = f"{document_unit.title or ''}\n{document_unit.extracted_summary or ''}\n{segment_text}".lower()

    specialists: list[str] = []
    utility_markers = [
        "bolletta",
        "fornitura",
        "data di emissione",
        "entro quando devo pagare",
        "totale bolletta",
        "numero cliente",
        "rif.bolletta",
        "pod",
        "pdr",
        "energia elettrica",
        "gas",
        "acqua",
    ]
    accounting_markers = [
        "bilancio preventivo",
        "rendiconto",
        "riparto",
        "preventivo ripartizioni",
        "saldo finale",
        "totale gestione",
        "esercizio",
        "spese deliberate",
        "importi",
        "totali",
    ]

    utility_score = sum(marker in text for marker in utility_markers)
    accounting_score = sum(marker in text for marker in accounting_markers)

    if doc_type == "bolletta" or (doc_type == "fattura" and utility_score >= 3) or utility_score >= 5:
        specialists.append("utility_bill")
    if doc_type in {"rendiconto_contabile", "riparto_spese"} or accounting_score >= 4:
        specialists.append("accounting_statement")
    return specialists


def ensure_specialist_jobs_for_scan_unit(session: Session, scan_unit_id: str | uuid.UUID) -> list[SpecialistJob]:
    parsed_scan_unit_id = _parse_uuid(scan_unit_id)
    document_units = session.execute(
        select(DocumentUnit)
        .where(DocumentUnit.scan_unit_id == parsed_scan_unit_id)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.specialist_jobs),
            selectinload(DocumentUnit.specialist_results),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.ocr_result),
        )
        .order_by(DocumentUnit.ordinal.asc())
    ).scalars().all()

    created_jobs: list[SpecialistJob] = []
    for document_unit in document_units:
        scan_unit = document_unit.scan_unit
        ocr_result = scan_unit.ocr_result if scan_unit else None
        if ocr_result is None:
            continue
        segment_text = extract_document_unit_text(document_unit, ocr_result)
        specialist_types = route_specialists_for_document_unit(document_unit, segment_text)
        input_version = f"{ocr_result.id}:{document_unit.start_page}-{document_unit.end_page}"
        for specialist_type in specialist_types:
            latest_job = session.execute(
                select(SpecialistJob)
                .where(
                    SpecialistJob.document_unit_id == document_unit.id,
                    SpecialistJob.specialist_type == specialist_type,
                )
                .order_by(SpecialistJob.created_at.desc())
            ).scalar_one_or_none()
            if latest_job and latest_job.status in {"queued", "pending", "processing", "succeeded"}:
                continue
            latest_result = session.execute(
                select(SpecialistResult)
                .where(
                    SpecialistResult.document_unit_id == document_unit.id,
                    SpecialistResult.specialist_type == specialist_type,
                )
                .order_by(SpecialistResult.created_at.desc())
            ).scalar_one_or_none()
            if latest_result is not None:
                result_input_version = (latest_result.result_json or {}).get("input_version")
                if result_input_version == input_version:
                    continue

            job = SpecialistJob(
                document_unit_id=document_unit.id,
                specialist_type=specialist_type,
                status="queued",
                input_version=input_version,
            )
            session.add(job)
            created_jobs.append(job)

    session.flush()
    return created_jobs


def mark_stale_specialist_jobs(session: Session, running_timeout_seconds: int, queued_timeout_seconds: int) -> int:
    now = _utcnow()
    updated = 0
    jobs = session.execute(
        select(SpecialistJob).where(SpecialistJob.status.in_(("queued", "pending", "processing")))
    ).scalars().all()
    for job in jobs:
        age_seconds = None
        if job.status == "processing" and job.started_at is not None:
            age_seconds = (now - job.started_at).total_seconds()
            if age_seconds > running_timeout_seconds:
                job.status = "failed"
                job.finished_at = now
                job.error_message = "Stale specialist job reconciled automatically."
                updated += 1
        elif job.status in {"queued", "pending"}:
            age_seconds = (now - job.created_at).total_seconds()
            if age_seconds > queued_timeout_seconds:
                job.status = "failed"
                job.finished_at = now
                job.error_message = "Stale queued specialist job reconciled automatically."
                updated += 1
    if updated:
        session.flush()
    return updated


def _parse_uuid(value: str | uuid.UUID) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(value)
