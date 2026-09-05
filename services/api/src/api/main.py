import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from redis import Redis
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session

from api.middleware import RequestContextMiddleware
from api.routers import knowledge
from common.api.schemas import (
    CreateJobRequest,
    DocumentAssetResponse,
    DocumentResponse,
    DocumentVersionResponse,
    JobResponse,
    ManualCommentCreate,
    ManualCommentUpdate,
    ManualCommentResponse,
    ManualResponse,
    OCRResponse,
    RemoteBackendStatus,
    ReadinessResponse,
    RuntimeMLSettings,
    RuntimeSettingsProbeResponse,
    RuntimeSettingsResponse,
    SystemStatusResponse,
    UploadResponse,
)
from common.application.runtime_settings import (
    load_runtime_settings,
    resolve_runtime_settings,
    save_runtime_settings,
)
from common.application.repositories import (
    AssetRepository,
    DocumentRepository,
    DocumentVersionRepository,
    JobRepository,
    OCRResultRepository,
)
from common.application.services import DocumentService, JobService, persist_upload_to_temp
from common.config import Settings, get_settings
from common.db.models import (
    DocumentAsset,
    DocumentUnit,
    IngestionJob,
    KnowledgeJob,
    ManualComment,
    OCRResult,
    ScanUnit,
    SpecialistJob,
    TopicProposal,
)
from common.db.schema import ensure_knowledge_schema
from common.db.session import engine, get_db_session
from common.domain.enums import AssetType, SourceType
from common.domain.exceptions import NotFoundError, ValidationError
from common.logging import configure_logging
from common.storage.backends import StorageBackend, get_storage_backend
from worker.tasks import process_ingestion_job
from knowledge_classifier.config import get_settings as get_knowledge_settings
from knowledge_worker.dispatch import dispatch_scan_unit_processing
from specialist_worker.dispatch import dispatch_specialist_job
from api.services.job_observability import summarize_jobs

configure_logging(get_settings().log_level)

app = FastAPI(title="megadoc api", version="0.1.0")
app.add_middleware(RequestContextMiddleware)
MANUAL_DIRECTORY = Path("/app/docs")
MANUAL_SLUGS = {"system": MANUAL_DIRECTORY / "system_manual.md"}


def _serialize_job(job, session: Session) -> JobResponse:
    job_service = JobService(session)
    is_stale, stale_reason = job_service.is_job_stale(job)
    return JobResponse.model_validate(
        {
            "id": job.id,
            "document_id": job.document_id,
            "job_type": job.job_type,
            "status": job.status,
            "priority": job.priority,
            "attempt_count": job.attempt_count,
            "error_message": job.error_message,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "is_stale": is_stale,
            "stale_reason": stale_reason,
        }
    )


@app.on_event("startup")
def ensure_database_schema() -> None:
    if os.getenv("MEGADOC_SKIP_STARTUP_SCHEMA") == "1":
        return
    ensure_knowledge_schema(engine)
    with Session(engine) as session:
        JobService(session).reconcile_stale_jobs()

# Include routers
app.include_router(knowledge.router)


def dispatch_ingestion_job(job_id: uuid.UUID, ocr_backend: str | None = None) -> None:
    settings = get_settings()
    if settings.celery_task_always_eager:
        process_ingestion_job(str(job_id), backend_override=ocr_backend)
        return
    process_ingestion_job.apply_async(
        args=[str(job_id)],
        kwargs={"backend_override": ocr_backend},
        queue=_ingestion_queue_for_backend(settings, ocr_backend),
    )


def _ingestion_queue_for_backend(settings: Settings, ocr_backend: str | None) -> str:
    if (ocr_backend or "").strip().lower() in {"llm_vision", "dots_native"}:
        return settings.ingestion_queue_llm_vision
    return settings.ingestion_queue_default


def get_settings_dep() -> Settings:
    return get_settings()


def db_session_dep():
    yield from get_db_session()


def get_storage_dep(settings: Annotated[Settings, Depends(get_settings_dep)]) -> StorageBackend:
    return get_storage_backend(settings)


def get_redis_dep(settings: Annotated[Settings, Depends(get_settings_dep)]) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def get_document_service_dep(
    session: Annotated[Session, Depends(db_session_dep)],
    settings: Annotated[Settings, Depends(get_settings_dep)],
    storage: Annotated[StorageBackend, Depends(get_storage_dep)],
) -> DocumentService:
    return DocumentService(session=session, settings=settings, storage=storage)


def get_job_service_dep(session: Annotated[Session, Depends(db_session_dep)]) -> JobService:
    return JobService(session=session)


def _load_manual(slug: str) -> tuple[str, str]:
    manual_path = MANUAL_SLUGS.get(slug)
    if manual_path is None or not manual_path.exists():
        raise HTTPException(status_code=404, detail="Manual not found.")
    markdown = manual_path.read_text(encoding="utf-8")
    title = "System Manual"
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return title, markdown


@app.post("/documents/upload", response_model=UploadResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    external_id: str | None = Form(default=None),
    auto_submit: bool = Query(default=True),
    ocr_backend: str | None = Query(default=None),
    document_service: DocumentService = Depends(get_document_service_dep),
    job_service: JobService = Depends(get_job_service_dep),
) -> UploadResponse:
    if file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Only PDF uploads are supported.")
    try:
        with NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            temp_path = Path(tmp.name)
        try:
            persist_upload_to_temp(file.file, temp_path)
            result = document_service.save_upload(
                temp_path,
                file.filename or "upload.pdf",
                SourceType.API,
                external_id=external_id,
            )
        finally:
            temp_path.unlink(missing_ok=True)
        job_id = None
        status = "stored"
        if auto_submit:
            job = job_service.create_ingest_job(result.document.id)
            dispatch_ingestion_job(job.id, ocr_backend=ocr_backend)
            job_id = job.id
            status = job.status
        return UploadResponse(
            document_id=result.document.id,
            version_id=result.version.id,
            status=status,
            deduplicated=result.deduplicated,
            job_id=job_id,
            sha256=result.document.sha256,
            size_bytes=result.document.size_bytes,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/jobs/ingest", response_model=JobResponse)
def create_ingest_job(
    payload: CreateJobRequest,
    job_service: JobService = Depends(get_job_service_dep),
) -> JobResponse:
    try:
        job = job_service.create_ingest_job(payload.document_id, payload.priority)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    dispatch_ingestion_job(job.id, ocr_backend=payload.ocr_backend)
    return _serialize_job(job, job_service.session)


@app.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    limit: int = Query(default=100, le=500),
    session: Session = Depends(db_session_dep),
) -> list[JobResponse]:
    JobService(session).reconcile_stale_jobs()
    rows = JobRepository(session).list(limit)
    return [_serialize_job(row, session) for row in rows]


@app.get("/jobs/background-activity")
def background_activity(session: Session = Depends(db_session_dep)) -> dict:
    return _background_activity(session)


@app.get("/jobs/metrics")
def job_metrics(
    hours: int = Query(default=24, ge=1, le=24 * 30),
    session: Session = Depends(db_session_dep),
) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    pipelines = {
        "ingestion": session.execute(
            select(IngestionJob).where(IngestionJob.created_at >= cutoff)
        ).scalars().all(),
        "knowledge": session.execute(
            select(KnowledgeJob).where(KnowledgeJob.created_at >= cutoff)
        ).scalars().all(),
        "specialists": session.execute(
            select(SpecialistJob).where(SpecialistJob.created_at >= cutoff)
        ).scalars().all(),
    }
    return {
        "window_hours": hours,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pipelines": {
            name: summarize_jobs(jobs, window_hours=hours)
            for name, jobs in pipelines.items()
        },
    }


@app.post("/jobs/{pipeline}/{job_id}/replay")
def replay_failed_job(
    pipeline: str,
    job_id: uuid.UUID,
    session: Session = Depends(db_session_dep),
) -> dict:
    if pipeline == "ingestion":
        failed_job = session.get(IngestionJob, job_id)
        if failed_job is None:
            raise HTTPException(status_code=404, detail="Ingestion job not found")
        if failed_job.status != "failed":
            raise HTTPException(status_code=409, detail="Only failed jobs can be replayed")
        active = JobRepository(session).find_active_ingest_job(failed_job.document_id)
        if active is not None:
            return {"status": "already_active", "pipeline": pipeline, "job_id": str(active.id)}
        replay = JobService(session).create_ingest_job(failed_job.document_id, priority=failed_job.priority)
        dispatch_ingestion_job(replay.id)
    elif pipeline == "knowledge":
        failed_job = session.get(KnowledgeJob, job_id)
        if failed_job is None:
            raise HTTPException(status_code=404, detail="Knowledge job not found")
        if failed_job.status != "failed":
            raise HTTPException(status_code=409, detail="Only failed jobs can be replayed")
        if failed_job.job_type != "full_processing":
            raise HTTPException(status_code=409, detail="Only full_processing knowledge jobs can be replayed here")
        active = session.execute(
            select(KnowledgeJob)
            .where(KnowledgeJob.scan_unit_id == failed_job.scan_unit_id)
            .where(KnowledgeJob.job_type == failed_job.job_type)
            .where(KnowledgeJob.status.in_(("queued", "pending", "processing", "running")))
            .order_by(KnowledgeJob.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if active is not None:
            return {"status": "already_active", "pipeline": pipeline, "job_id": str(active.id)}
        replay = KnowledgeJob(
            scan_unit_id=failed_job.scan_unit_id,
            job_type=failed_job.job_type,
            status="queued",
        )
        session.add(replay)
        session.commit()
        session.refresh(replay)
        dispatch_scan_unit_processing(str(replay.scan_unit_id))
    elif pipeline == "specialists":
        failed_job = session.get(SpecialistJob, job_id)
        if failed_job is None:
            raise HTTPException(status_code=404, detail="Specialist job not found")
        if failed_job.status != "failed":
            raise HTTPException(status_code=409, detail="Only failed jobs can be replayed")
        active = session.execute(
            select(SpecialistJob)
            .where(SpecialistJob.document_unit_id == failed_job.document_unit_id)
            .where(SpecialistJob.specialist_type == failed_job.specialist_type)
            .where(SpecialistJob.status.in_(("queued", "pending", "processing", "running")))
            .order_by(SpecialistJob.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if active is not None:
            return {"status": "already_active", "pipeline": pipeline, "job_id": str(active.id)}
        replay = SpecialistJob(
            document_unit_id=failed_job.document_unit_id,
            specialist_type=failed_job.specialist_type,
            status="queued",
            input_version=failed_job.input_version,
            routing_confidence=failed_job.routing_confidence,
            routing_rationale=failed_job.routing_rationale,
        )
        session.add(replay)
        session.commit()
        session.refresh(replay)
        dispatch_specialist_job(str(replay.id), replay.specialist_type)
    else:
        raise HTTPException(status_code=400, detail="Unknown pipeline")
    return {"status": "replayed", "pipeline": pipeline, "job_id": str(replay.id)}


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: uuid.UUID, session: Session = Depends(db_session_dep)) -> JobResponse:
    JobService(session).reconcile_stale_jobs()
    job = JobRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _serialize_job(job, session)


def _background_activity(session: Session) -> dict:
    now = datetime.now(timezone.utc)
    active_statuses = {"queued", "pending", "processing", "running"}
    terminal_statuses = {"succeeded", "failed", "completed"}

    ingestion_jobs = session.execute(
        select(IngestionJob).order_by(IngestionJob.created_at.desc()).limit(80)
    ).scalars().all()
    knowledge_jobs = session.execute(
        select(KnowledgeJob).order_by(KnowledgeJob.created_at.desc()).limit(120)
    ).scalars().all()
    specialist_jobs = session.execute(
        select(SpecialistJob).order_by(SpecialistJob.created_at.desc()).limit(120)
    ).scalars().all()

    ingestion_items = [_activity_item_from_ingestion(job, session, now) for job in ingestion_jobs]
    knowledge_items = [_activity_item_from_knowledge(job, now) for job in knowledge_jobs]
    specialist_items = [_activity_item_from_specialist(job, session, now) for job in specialist_jobs]
    all_items = ingestion_items + knowledge_items + specialist_items
    _enrich_activity_estimates(all_items)

    active_items = [
        item for item in all_items
        if item["status"] in active_statuses and not item["is_possibly_stale"]
    ]
    stale_items = [
        item for item in all_items
        if item["status"] in active_statuses and item["is_possibly_stale"]
    ]
    failed_items = [item for item in all_items if item["status"] == "failed"]
    recent_items = sorted(
        all_items,
        key=lambda item: item.get("started_at") or item.get("created_at") or "",
        reverse=True,
    )[:30]

    return {
        "status": "idle" if not active_items else "active",
        "is_idle": not active_items,
        "active_count": len(active_items),
        "possibly_stale_count": len(stale_items),
        "failed_count": len(failed_items),
        "updated_at": now.isoformat(),
        "pipelines": {
            "ingestion": _activity_pipeline_summary(ingestion_items, active_statuses, terminal_statuses),
            "knowledge": _activity_pipeline_summary(knowledge_items, active_statuses, terminal_statuses),
            "specialists": _activity_pipeline_summary(specialist_items, active_statuses, terminal_statuses),
        },
        "active_jobs": sorted(
            active_items,
            key=lambda item: item.get("started_at") or item.get("created_at") or "",
            reverse=True,
        )[:20],
        "possibly_stale_jobs": sorted(
            stale_items,
            key=lambda item: item.get("started_at") or item.get("created_at") or "",
            reverse=True,
        )[:20],
        "failed_jobs": sorted(
            failed_items,
            key=lambda item: item.get("finished_at") or item.get("created_at") or "",
            reverse=True,
        )[:20],
        "recent_jobs": recent_items,
    }


def _activity_pipeline_summary(items: list[dict], active_statuses: set[str], terminal_statuses: set[str]) -> dict:
    by_status: dict[str, int] = {}
    for item in items:
        by_status[item["status"]] = by_status.get(item["status"], 0) + 1
    completed_durations = [
        item["duration_seconds"] for item in items
        if item.get("duration_seconds") is not None and item["status"] in terminal_statuses
    ]
    mean_duration = sum(completed_durations) / len(completed_durations) if completed_durations else None
    return {
        "total": len(items),
        "active": sum(1 for item in items if item["status"] in active_statuses and not item["is_possibly_stale"]),
        "possibly_stale": sum(1 for item in items if item["status"] in active_statuses and item["is_possibly_stale"]),
        "failed": by_status.get("failed", 0),
        "done": sum(count for status, count in by_status.items() if status in terminal_statuses),
        "by_status": by_status,
        "mean_duration_seconds": round(mean_duration, 1) if mean_duration is not None else None,
        "throughput_per_hour": _recent_throughput(items),
    }


def _activity_item_base(
    *,
    pipeline: str,
    job_id: uuid.UUID,
    status: str,
    job_type: str,
    attempt_count: int,
    error_message: str | None,
    created_at: datetime,
    started_at: datetime | None,
    finished_at: datetime | None,
    now: datetime,
    stale_after_seconds: int,
) -> dict:
    anchor = started_at or created_at
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)
    age_seconds = int((now - anchor).total_seconds())
    duration_seconds = None
    if started_at and finished_at:
        duration_seconds = max(0, int((finished_at - started_at).total_seconds()))
    return {
        "pipeline": pipeline,
        "id": str(job_id),
        "status": status,
        "job_type": job_type,
        "attempt_count": attempt_count,
        "error_message": error_message,
        "created_at": created_at.isoformat(),
        "started_at": started_at.isoformat() if started_at else None,
        "finished_at": finished_at.isoformat() if finished_at else None,
        "age_seconds": max(0, age_seconds),
        "duration_seconds": duration_seconds,
        "eta_seconds": None,
        "queue_position": None,
        "waiting_reason": None,
        "is_possibly_stale": status in {"queued", "pending", "processing", "running"} and age_seconds > stale_after_seconds,
    }


def _enrich_activity_estimates(items: list[dict]) -> None:
    active_ingestion = any(
        item["pipeline"] == "ingestion" and item["status"] in {"queued", "running"}
        for item in items
    )
    for pipeline in {item["pipeline"] for item in items}:
        pipeline_items = [item for item in items if item["pipeline"] == pipeline]
        durations = [item["duration_seconds"] for item in pipeline_items if item.get("duration_seconds")]
        average = sum(durations) / len(durations) if durations else None
        queued = sorted(
            [item for item in pipeline_items if item["status"] in {"queued", "pending"}],
            key=lambda item: item["created_at"],
        )
        for position, item in enumerate(queued, start=1):
            item["queue_position"] = position
            item["eta_seconds"] = round(average * position) if average is not None else None
            if pipeline == "knowledge" and active_ingestion:
                item["waiting_reason"] = "In attesa che la coda OCR si svuoti; OCR ha priorita'."
            else:
                item["waiting_reason"] = f"In attesa del worker {pipeline}, posizione {position}."
        for item in pipeline_items:
            if item["status"] in {"processing", "running"}:
                item["waiting_reason"] = f"Elaborazione {pipeline} in corso."
                if average is not None:
                    item["eta_seconds"] = max(0, round(average - item["age_seconds"]))
            if item["is_possibly_stale"]:
                item["waiting_reason"] = item.get("stale_reason") or "Job oltre la durata attesa."


def _recent_throughput(items: list[dict]) -> float:
    finished = [item for item in items if item.get("finished_at") and item["status"] in {"succeeded", "completed"}]
    if not finished:
        return 0.0
    timestamps = [datetime.fromisoformat(item["finished_at"]) for item in finished]
    span_hours = max((max(timestamps) - min(timestamps)).total_seconds() / 3600, 1 / 60)
    return round(len(finished) / span_hours, 2)


def _activity_item_from_ingestion(job: IngestionJob, session: Session, now: datetime) -> dict:
    item = _activity_item_base(
        pipeline="ingestion",
        job_id=job.id,
        status=job.status,
        job_type=job.job_type,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        now=now,
        stale_after_seconds=20 * 60,
    )
    is_stale, stale_reason = JobService(session).is_job_stale(job)
    item.update({
        "document_id": str(job.document_id),
        "scan_unit_id": None,
        "document_unit_id": None,
        "label": f"Ingestione {job.job_type}",
        "is_possibly_stale": bool(is_stale or item["is_possibly_stale"]),
        "stale_reason": stale_reason,
    })
    return item


def _activity_item_from_knowledge(job: KnowledgeJob, now: datetime) -> dict:
    item = _activity_item_base(
        pipeline="knowledge",
        job_id=job.id,
        status=job.status,
        job_type=job.job_type,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        now=now,
        stale_after_seconds=20 * 60,
    )
    scan_unit = job.scan_unit
    item.update({
        "document_id": str(scan_unit.source_document_id) if scan_unit else None,
        "scan_unit_id": str(job.scan_unit_id),
        "document_unit_id": None,
        "label": f"Knowledge {job.job_type}",
        "stale_reason": "Knowledge job attivo da molto tempo." if item["is_possibly_stale"] else None,
    })
    return item


def _activity_item_from_specialist(job: SpecialistJob, session: Session, now: datetime) -> dict:
    item = _activity_item_base(
        pipeline="specialists",
        job_id=job.id,
        status=job.status,
        job_type=job.specialist_type,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        now=now,
        stale_after_seconds=30 * 60,
    )
    document_unit = session.get(DocumentUnit, job.document_unit_id)
    scan_unit = document_unit.scan_unit if document_unit else None
    item.update({
        "document_id": str(scan_unit.source_document_id) if scan_unit else None,
        "scan_unit_id": str(document_unit.scan_unit_id) if document_unit else None,
        "document_unit_id": str(job.document_unit_id),
        "label": f"Specialista {job.specialist_type}",
        "stale_reason": "Specialist job attivo da molto tempo." if item["is_possibly_stale"] else None,
    })
    return item


@app.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    limit: int = Query(default=100, le=500),
    session: Session = Depends(db_session_dep),
) -> list[DocumentResponse]:
    rows = DocumentRepository(session).list(limit)
    if not rows:
        return []

    doc_ids = [row.id for row in rows]

    # Batch: scan unit, document unit and actionable review counts per document.
    counts_query = (
        select(
            ScanUnit.source_document_id,
            func.count(func.distinct(ScanUnit.id)).label("su_count"),
            func.count(DocumentUnit.id).label("du_count"),
            func.count(DocumentUnit.id)
            .filter(DocumentUnit.review_status == "needs_review")
            .label("needs_review_du_count"),
            func.count(TopicProposal.id)
            .filter(TopicProposal.proposal_status == "proposed")
            .label("pending_proposal_count"),
            func.count(func.distinct(ScanUnit.id))
            .filter(
                or_(
                    DocumentUnit.review_status == "needs_review",
                    TopicProposal.proposal_status == "proposed",
                )
            )
            .label("needs_review_su_count"),
        )
        .outerjoin(DocumentUnit, DocumentUnit.scan_unit_id == ScanUnit.id)
        .outerjoin(TopicProposal, TopicProposal.source_document_unit_id == DocumentUnit.id)
        .where(ScanUnit.source_document_id.in_(doc_ids))
        .group_by(ScanUnit.source_document_id)
    )
    counts_map: dict[uuid.UUID, tuple[int, int, int, int, int]] = {}
    for r in session.execute(counts_query).all():
        counts_map[r.source_document_id] = (
            r.su_count,
            r.du_count,
            r.needs_review_du_count,
            r.pending_proposal_count,
            r.needs_review_su_count,
        )

    # Batch: latest OCR result per document (for preflight info)
    latest_ocr_subq = (
        select(OCRResult.id)
        .where(OCRResult.document_id.in_(doc_ids))
        .order_by(OCRResult.document_id, OCRResult.created_at.desc())
        .distinct(OCRResult.document_id)
        .subquery()
    )
    ocr_rows = session.execute(
        select(OCRResult).where(OCRResult.id.in_(latest_ocr_subq))
    ).scalars().all()
    ocr_map: dict[uuid.UUID, OCRResult] = {r.document_id: r for r in ocr_rows}

    # Batch: latest ingestion job per document
    latest_job_subq = (
        select(IngestionJob.id)
        .where(IngestionJob.document_id.in_(doc_ids))
        .order_by(IngestionJob.document_id, IngestionJob.created_at.desc())
        .distinct(IngestionJob.document_id)
        .subquery()
    )
    job_rows = session.execute(
        select(IngestionJob).where(IngestionJob.id.in_(latest_job_subq))
    ).scalars().all()
    job_map: dict[uuid.UUID, IngestionJob] = {r.document_id: r for r in job_rows}

    result: list[DocumentResponse] = []
    for row in rows:
        su_count, du_count, needs_review_du_count, pending_proposal_count, needs_review_su_count = counts_map.get(
            row.id, (0, 0, 0, 0, 0)
        )
        review_issue_count = needs_review_du_count + pending_proposal_count

        rotation_applied: int | None = None
        page_order_reversed: bool | None = None
        ocr = ocr_map.get(row.id)
        if ocr and ocr.confidence_summary:
            orientation = ocr.confidence_summary.get("orientation_preprocess", {})
            if isinstance(orientation, dict):
                rotation_applied = orientation.get("rotation_applied")
                page_order_reversed = orientation.get("page_order_reversed", False)

        job = job_map.get(row.id)
        ingestion_status = job.status if job else None
        ingestion_error = job.error_message if job else None

        result.append(
            DocumentResponse(
                id=row.id,
                external_id=row.external_id,
                original_filename=row.original_filename,
                mime_type=row.mime_type,
                sha256=row.sha256,
                size_bytes=row.size_bytes,
                source_type=row.source_type,
                created_at=row.created_at,
                scan_unit_count=su_count,
                document_unit_count=du_count,
                rotation_applied=rotation_applied,
                page_order_reversed=page_order_reversed,
                ingestion_status=ingestion_status,
                ingestion_error=ingestion_error,
                knowledge_review_status="needs_review" if review_issue_count else "clear",
                knowledge_review_issue_count=review_issue_count,
                needs_review_scan_unit_count=needs_review_su_count,
            )
        )

    return result


@app.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: uuid.UUID, session: Session = Depends(db_session_dep)) -> DocumentResponse:
    document = DocumentRepository(session).get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Scan unit and document unit counts
    count_result = session.execute(
        select(
            func.count(func.distinct(ScanUnit.id)).label("su_count"),
            func.count(DocumentUnit.id).label("du_count"),
            func.count(DocumentUnit.id)
            .filter(DocumentUnit.review_status == "needs_review")
            .label("needs_review_du_count"),
            func.count(TopicProposal.id)
            .filter(TopicProposal.proposal_status == "proposed")
            .label("pending_proposal_count"),
            func.count(func.distinct(ScanUnit.id))
            .filter(
                or_(
                    DocumentUnit.review_status == "needs_review",
                    TopicProposal.proposal_status == "proposed",
                )
            )
            .label("needs_review_su_count"),
        )
        .outerjoin(DocumentUnit, DocumentUnit.scan_unit_id == ScanUnit.id)
        .outerjoin(TopicProposal, TopicProposal.source_document_unit_id == DocumentUnit.id)
        .where(ScanUnit.source_document_id == document.id)
    ).one()

    # Latest OCR result for preflight info
    ocr_result = session.execute(
        select(OCRResult)
        .where(OCRResult.document_id == document.id)
        .order_by(OCRResult.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    rotation_applied: int | None = None
    page_order_reversed: bool | None = None
    if ocr_result and ocr_result.confidence_summary:
        orientation = ocr_result.confidence_summary.get("orientation_preprocess", {})
        if isinstance(orientation, dict):
            rotation_applied = orientation.get("rotation_applied")
            page_order_reversed = orientation.get("page_order_reversed", False)

    # Latest ingestion job
    latest_job = session.execute(
        select(IngestionJob)
        .where(IngestionJob.document_id == document.id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    return DocumentResponse(
        id=document.id,
        external_id=document.external_id,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        sha256=document.sha256,
        size_bytes=document.size_bytes,
        source_type=document.source_type,
        created_at=document.created_at,
        scan_unit_count=count_result.su_count,
        document_unit_count=count_result.du_count,
        rotation_applied=rotation_applied,
        page_order_reversed=page_order_reversed,
        ingestion_status=latest_job.status if latest_job else None,
        ingestion_error=latest_job.error_message if latest_job else None,
        knowledge_review_status="needs_review"
        if count_result.needs_review_du_count + count_result.pending_proposal_count
        else "clear",
        knowledge_review_issue_count=count_result.needs_review_du_count + count_result.pending_proposal_count,
        needs_review_scan_unit_count=count_result.needs_review_su_count,
    )


OCR_ASSET_TYPES = {AssetType.MARKDOWN, AssetType.TEXT, AssetType.OCR_JSON, AssetType.PREFLIGHT_JSON, AssetType.OCR_REFINEMENT_JSON}


@app.post("/documents/{document_id}/reingest")
def reingest_document(
    document_id: uuid.UUID,
    ocr_backend: str | None = Query(default=None),
    session: Session = Depends(db_session_dep),
) -> DocumentResponse:
    """Delete all OCR artifacts and ingestion jobs for a document, then re-queue ingestion."""
    document = DocumentRepository(session).get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Delete OCR-related document assets (S3 artifacts remain orphaned — acceptable for dev)
    session.execute(
        delete(DocumentAsset).where(
            DocumentAsset.document_id == document.id,
            DocumentAsset.asset_type.in_(OCR_ASSET_TYPES),
        )
    )

    # Delete OCR results (cascade deletes scan_units → document_units, knowledge_jobs, etc.)
    session.execute(delete(OCRResult).where(OCRResult.document_id == document.id))

    # Delete ingestion jobs
    session.execute(delete(IngestionJob).where(IngestionJob.document_id == document.id))

    session.commit()

    # Create a new ingestion job
    job_service = JobService(session)
    job = job_service.create_ingest_job(document.id)
    dispatch_ingestion_job(job.id, ocr_backend=ocr_backend)

    # Return updated document info
    return get_document(document_id, session)


@app.get("/documents/{document_id}/versions", response_model=list[DocumentVersionResponse])
def list_document_versions(
    document_id: uuid.UUID, session: Session = Depends(db_session_dep)
) -> list[DocumentVersionResponse]:
    document = DocumentRepository(session).get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    rows = DocumentVersionRepository(session).list_for_document(document_id)
    return [DocumentVersionResponse.model_validate(row, from_attributes=True) for row in rows]


@app.get("/documents/{document_id}/assets", response_model=list[DocumentAssetResponse])
def list_document_assets(
    document_id: uuid.UUID, session: Session = Depends(db_session_dep)
) -> list[DocumentAssetResponse]:
    document = DocumentRepository(session).get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    rows = AssetRepository(session).list_for_document(document_id)
    return [DocumentAssetResponse.model_validate(row, from_attributes=True) for row in rows]


@app.get("/manuals/{manual_slug}", response_model=ManualResponse)
def get_manual(manual_slug: str, session: Session = Depends(db_session_dep)) -> ManualResponse:
    title, markdown = _load_manual(manual_slug)
    comments = (
        session.query(ManualComment)
        .filter(ManualComment.manual_slug == manual_slug)
        .order_by(
            text(
                "CASE status WHEN 'open' THEN 0 WHEN 'wontfix' THEN 1 WHEN 'resolved' THEN 2 ELSE 3 END"
            ),
            ManualComment.created_at.desc(),
        )
        .all()
    )
    return ManualResponse(
        slug=manual_slug,
        title=title,
        markdown=markdown,
        comments=[ManualCommentResponse.model_validate(comment, from_attributes=True) for comment in comments],
    )


@app.post("/manuals/{manual_slug}/comments", response_model=ManualCommentResponse, status_code=201)
def create_manual_comment(
    manual_slug: str,
    payload: ManualCommentCreate,
    session: Session = Depends(db_session_dep),
) -> ManualCommentResponse:
    _load_manual(manual_slug)
    comment = ManualComment(
        manual_slug=manual_slug,
        selected_text=payload.selected_text.strip(),
        selection_start=payload.selection_start,
        selection_end=payload.selection_end,
        comment_text=payload.comment_text.strip(),
        author_name=(payload.author_name or "").strip() or None,
    )
    if not comment.selected_text:
        raise HTTPException(status_code=400, detail="selected_text is required.")
    if not comment.comment_text:
        raise HTTPException(status_code=400, detail="comment_text is required.")
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return ManualCommentResponse.model_validate(comment, from_attributes=True)


@app.patch("/manuals/{manual_slug}/comments/{comment_id}", response_model=ManualCommentResponse)
def update_manual_comment(
    manual_slug: str,
    comment_id: uuid.UUID,
    payload: ManualCommentUpdate,
    session: Session = Depends(db_session_dep),
) -> ManualCommentResponse:
    _load_manual(manual_slug)
    if payload.status not in {"open", "resolved", "wontfix"}:
        raise HTTPException(status_code=400, detail="Invalid manual comment status.")
    comment = (
        session.query(ManualComment)
        .filter(ManualComment.id == comment_id, ManualComment.manual_slug == manual_slug)
        .one_or_none()
    )
    if comment is None:
        raise HTTPException(status_code=404, detail="Manual comment not found.")

    comment.status = payload.status
    comment.resolution_note = (payload.resolution_note or "").strip() or None
    if payload.status == "open":
        comment.resolved_by = None
        comment.resolved_at = None
    else:
        comment.resolved_by = (payload.resolved_by or "").strip() or None
        comment.resolved_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(comment)
    return ManualCommentResponse.model_validate(comment, from_attributes=True)


@app.get("/documents/{document_id}/ocr", response_model=OCRResponse)
def get_document_ocr(document_id: uuid.UUID, session: Session = Depends(db_session_dep)) -> OCRResponse:
    result = OCRResultRepository(session).get_latest_for_document(document_id)
    if result is None:
        raise HTTPException(status_code=404, detail="OCR result not found.")
    return OCRResponse.model_validate(result, from_attributes=True)


@app.get("/documents/{document_id}/download")
def download_document(
    document_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
    disposition: str = "attachment",
    session: Session = Depends(db_session_dep),
    storage: StorageBackend = Depends(get_storage_dep),
) -> Response:
    document = DocumentRepository(session).get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    versions = DocumentVersionRepository(session)
    version = versions.get(version_id) if version_id is not None else versions.get_latest_for_document(document_id)
    if version is None or version.document_id != document_id:
        raise HTTPException(status_code=404, detail="Document version not found.")

    content = storage.read_bytes(version.storage_bucket, version.storage_object_key)
    content_disposition = "inline" if disposition == "inline" else "attachment"
    headers = {"Content-Disposition": f'{content_disposition}; filename="{document.original_filename}"'}
    return Response(content=content, media_type=document.mime_type, headers=headers)


@app.get("/documents/{document_id}/assets/{asset_id}/download")
def download_document_asset(
    document_id: uuid.UUID,
    asset_id: uuid.UUID,
    session: Session = Depends(db_session_dep),
    storage: StorageBackend = Depends(get_storage_dep),
) -> Response:
    document = DocumentRepository(session).get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")

    asset = AssetRepository(session).get(asset_id)
    if asset is None or asset.document_id != document_id:
        raise HTTPException(status_code=404, detail="Document asset not found.")

    filename = Path(asset.storage_object_key).name
    content = storage.read_bytes(asset.storage_bucket, asset.storage_object_key)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return Response(content=content, media_type=asset.content_type, headers=headers)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", response_model=ReadinessResponse)
def ready(
    session: Session = Depends(db_session_dep),
    redis: Redis = Depends(get_redis_dep),
    storage: StorageBackend = Depends(get_storage_dep),
) -> ReadinessResponse:
    db_status = "ok"
    redis_status = "ok"
    storage_status = "ok"
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"
    try:
        redis.ping()
    except Exception:
        redis_status = "error"
    try:
        storage.healthcheck()
    except Exception:
        storage_status = "error"
    overall = "ok" if {db_status, redis_status, storage_status} == {"ok"} else "degraded"
    return ReadinessResponse(
        status=overall, database=db_status, redis=redis_status, storage=storage_status
    )


@app.get("/system/status", response_model=SystemStatusResponse)
def system_status(
    session: Session = Depends(db_session_dep),
    redis: Redis = Depends(get_redis_dep),
    storage: StorageBackend = Depends(get_storage_dep),
    settings: Settings = Depends(get_settings_dep),
) -> SystemStatusResponse:
    db_status = "ok"
    redis_status = "ok"
    storage_status = "ok"
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"
    try:
        redis.ping()
    except Exception:
        redis_status = "error"
    try:
        storage.healthcheck()
    except Exception:
        storage_status = "error"

    runtime = _effective_runtime_settings(session, settings)
    ocr_status = _probe_ocr_backend(settings, runtime)
    llm_status = _probe_llm_backend(runtime)

    statuses = {
        db_status,
        redis_status,
        storage_status,
        ocr_status.status,
        llm_status.status,
    }
    overall = "ok"
    if "error" in statuses:
        overall = "error"
    elif "degraded" in statuses:
        overall = "degraded"

    return SystemStatusResponse(
        status=overall,
        database=db_status,
        redis=redis_status,
        storage=storage_status,
        ocr_backend=ocr_status,
        llm_backend=llm_status,
    )


@app.get("/settings/runtime", response_model=RuntimeSettingsResponse)
def get_runtime_settings(
    session: Session = Depends(db_session_dep),
    settings: Settings = Depends(get_settings_dep),
) -> RuntimeSettingsResponse:
    defaults = _runtime_setting_defaults(settings)
    overrides = load_runtime_settings(session)
    return RuntimeSettingsResponse(
        values=RuntimeMLSettings(**resolve_runtime_settings(session, defaults)),
        environment_defaults=RuntimeMLSettings(**defaults),
        overridden_keys=sorted(overrides),
    )


@app.put("/settings/runtime", response_model=RuntimeSettingsResponse)
def put_runtime_settings(
    payload: RuntimeMLSettings,
    session: Session = Depends(db_session_dep),
    settings: Settings = Depends(get_settings_dep),
) -> RuntimeSettingsResponse:
    values = payload.model_dump()
    _validate_runtime_endpoints(values)
    try:
        save_runtime_settings(session, values)
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    defaults = _runtime_setting_defaults(settings)
    return RuntimeSettingsResponse(
        values=payload,
        environment_defaults=RuntimeMLSettings(**defaults),
        overridden_keys=sorted(values),
    )


@app.post("/settings/runtime/probe", response_model=RuntimeSettingsProbeResponse)
def probe_runtime_settings(payload: RuntimeMLSettings) -> RuntimeSettingsProbeResponse:
    values = payload.model_dump()
    _validate_runtime_endpoints(values)
    probes = [
        _probe_openai_compatible_backend(
            name="knowledge_llm",
            endpoint=values["llm_endpoint"],
            model=values["llm_model"],
            api_key=get_knowledge_settings().llm_api_key,
            timeout_seconds=10,
        ),
        _probe_openai_compatible_backend(
            name="embeddings",
            endpoint=values["embedding_endpoint"],
            model=values["embedding_model"],
            api_key=get_knowledge_settings().llm_api_key,
            timeout_seconds=10,
        ),
        _probe_openai_compatible_backend(
            name="ocr:dots_native",
            endpoint=values["ocr_dots_endpoint"],
            model=values["ocr_dots_model"],
            api_key=get_settings().ocr_dots_native_api_key,
            timeout_seconds=10,
        ),
        _probe_openai_compatible_backend(
            name="ocr:llm_vision",
            endpoint=values["ocr_vision_endpoint"],
            model=values["ocr_vision_model"],
            api_key=get_settings().ocr_llm_vision_api_key,
            timeout_seconds=10,
        ),
    ]
    return RuntimeSettingsProbeResponse(backends=probes)


def _runtime_setting_defaults(settings: Settings) -> dict[str, str]:
    knowledge = get_knowledge_settings()
    llm_endpoint = os.getenv("KN_WORKER_LLM_ENDPOINT", knowledge.llm_endpoint)
    return {
        "llm_endpoint": llm_endpoint,
        "llm_model": knowledge.llm_model,
        "embedding_endpoint": knowledge.embedding_endpoint or llm_endpoint,
        "embedding_model": knowledge.embedding_model,
        "ocr_vision_endpoint": settings.ocr_llm_vision_endpoint,
        "ocr_vision_model": settings.ocr_llm_vision_model,
        "ocr_dots_endpoint": os.getenv(
            "OCR_WORKER_DOTS_NATIVE_ENDPOINT", settings.ocr_dots_native_endpoint
        ),
        "ocr_dots_model": settings.ocr_dots_native_model,
    }


def _effective_runtime_settings(session: Session, settings: Settings) -> dict[str, str]:
    return resolve_runtime_settings(session, _runtime_setting_defaults(settings))


def _validate_runtime_endpoints(values: dict[str, str]) -> None:
    for key in ("llm_endpoint", "embedding_endpoint", "ocr_vision_endpoint", "ocr_dots_endpoint"):
        value = values[key].strip()
        if not value.startswith(("http://", "https://", "mock://")):
            raise HTTPException(status_code=422, detail=f"{key} must be an HTTP(S) or mock URL")


def _probe_ocr_backend(settings: Settings, runtime: dict[str, str]) -> RemoteBackendStatus:
    backend = (settings.ocr_backend or "").strip().lower()
    if backend not in {"dots_native", "llm_vision"}:
        return RemoteBackendStatus(
            name=f"ocr:{backend or 'docling'}",
            status="ok",
            detail="Backend OCR locale, nessuna dipendenza remota richiesta.",
            server_reachable=True,
            model_available=None,
        )
    if backend == "dots_native":
        endpoint = runtime["ocr_dots_endpoint"]
        model = runtime["ocr_dots_model"]
        api_key = settings.ocr_dots_native_api_key
    else:
        endpoint = runtime["ocr_vision_endpoint"]
        model = runtime["ocr_vision_model"]
        api_key = settings.ocr_llm_vision_api_key
    return _probe_openai_compatible_backend(
        name=f"ocr:{backend}",
        endpoint=endpoint,
        model=model,
        api_key=api_key,
    )


def _probe_llm_backend(runtime: dict[str, str]) -> RemoteBackendStatus:
    kn_settings = get_knowledge_settings()
    if runtime["llm_endpoint"].startswith("mock://"):
        return RemoteBackendStatus(
            name="knowledge_llm",
            status="ok",
            endpoint=runtime["llm_endpoint"],
            model=runtime["llm_model"],
            detail="Mock LLM attivo.",
            server_reachable=True,
            model_available=True,
        )
    return _probe_openai_compatible_backend(
        name="knowledge_llm",
        endpoint=runtime["llm_endpoint"],
        model=runtime["llm_model"],
        api_key=kn_settings.llm_api_key,
    )


def _probe_openai_compatible_backend(
    *,
    name: str,
    endpoint: str,
    model: str | None,
    api_key: str | None,
    timeout_seconds: float = 2.5,
) -> RemoteBackendStatus:
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    root = endpoint.rstrip("/")
    if root.endswith("/v1"):
        health_url = root[:-3] + "/health"
    else:
        health_url = root + "/health"
    models_url = root + "/models"

    server_reachable = False
    model_available: bool | None = None
    latency_ms: int | None = None
    detail: str | None = None

    active_endpoint = endpoint
    model_ids: set[str] = set()
    catalog_verified = False
    try:
        health_request = UrlRequest(health_url, headers=headers, method="GET")
        started = datetime.now(timezone.utc)
        with urlopen(health_request, timeout=timeout_seconds) as response:
            response.read()
        latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        server_reachable = 200 <= getattr(response, "status", 200) < 300
    except Exception as exc:
        detail = f"Health check failed: {exc}"

    try:
        models_request = UrlRequest(models_url, headers=headers, method="GET")
        started = datetime.now(timezone.utc)
        with urlopen(models_request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if latency_ms is None:
            latency_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        server_reachable = True
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise ValueError("Risposta /models non conforme: atteso un elenco data.")
        models = payload["data"]
        if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in models):
            raise ValueError("Risposta /models non conforme: identificatori modello mancanti.")
        model_ids = {
            item.get("id")
            for item in models
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        catalog_verified = True
        detail = None
        if model:
            model_available = model in model_ids
            if not model_available:
                detail = f"Server raggiungibile ma modello non disponibile: {model}"
        else:
            model_available = None
    except HTTPError as exc:
        if exc.code == 404 and server_reachable:
            model_available = None
            detail = "Server raggiungibile; elenco modelli non esposto da /v1/models."
        else:
            detail = f"Model listing failed: HTTP {exc.code}"
    except URLError as exc:
        detail = f"Elenco modelli non verificabile: {exc.reason}"
    except Exception as exc:
        detail = f"Elenco modelli non verificabile: {exc}"

    status = "ok"
    if not server_reachable:
        status = "error"
    elif not catalog_verified or model_available is False:
        status = "degraded"

    if detail is None and status == "ok":
        detail = "Catalogo modelli verificato; generazione non testata."

    return RemoteBackendStatus(
        name=name,
        status=status,
        endpoint=active_endpoint,
        model=model,
        detail=detail,
        server_reachable=server_reachable,
        model_available=model_available,
        latency_ms=latency_ms,
        available_models=sorted(model_ids),
    )
