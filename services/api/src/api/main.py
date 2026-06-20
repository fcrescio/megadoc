import uuid
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from redis import Redis
from sqlalchemy import delete, func, select, text
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
    SystemStatusResponse,
    UploadResponse,
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
from common.db.models import DocumentAsset, DocumentUnit, IngestionJob, ManualComment, OCRResult, ScanUnit
from common.db.schema import ensure_knowledge_schema
from common.db.session import engine, get_db_session
from common.domain.enums import AssetType, SourceType
from common.domain.exceptions import NotFoundError, ValidationError
from common.logging import configure_logging
from common.storage.backends import StorageBackend, get_storage_backend
from worker.tasks import process_ingestion_job
from knowledge_classifier.config import get_settings as get_knowledge_settings

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


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: uuid.UUID, session: Session = Depends(db_session_dep)) -> JobResponse:
    JobService(session).reconcile_stale_jobs()
    job = JobRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return _serialize_job(job, session)


@app.get("/documents", response_model=list[DocumentResponse])
def list_documents(
    limit: int = Query(default=100, le=500),
    session: Session = Depends(db_session_dep),
) -> list[DocumentResponse]:
    rows = DocumentRepository(session).list(limit)
    if not rows:
        return []

    doc_ids = [row.id for row in rows]

    # Batch: scan unit and document unit counts per document
    counts_query = (
        select(
            ScanUnit.source_document_id,
            func.count(ScanUnit.id).label("su_count"),
            func.count(DocumentUnit.id).label("du_count"),
        )
        .outerjoin(DocumentUnit, DocumentUnit.scan_unit_id == ScanUnit.id)
        .where(ScanUnit.source_document_id.in_(doc_ids))
        .group_by(ScanUnit.source_document_id)
    )
    counts_map: dict[uuid.UUID, tuple[int, int]] = {}
    for r in session.execute(counts_query).all():
        counts_map[r.source_document_id] = (r.su_count, r.du_count)

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
        su_count, du_count = counts_map.get(row.id, (0, 0))

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
            func.count(ScanUnit.id).label("su_count"),
            func.count(DocumentUnit.id).label("du_count"),
        )
        .outerjoin(DocumentUnit, DocumentUnit.scan_unit_id == ScanUnit.id)
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

    ocr_status = _probe_ocr_backend(settings)
    llm_status = _probe_llm_backend(settings)

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


def _probe_ocr_backend(settings: Settings) -> RemoteBackendStatus:
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
        endpoint = os.getenv("OCR_WORKER_DOTS_NATIVE_ENDPOINT", settings.ocr_dots_native_endpoint)
        model = settings.ocr_dots_native_model
        api_key = settings.ocr_dots_native_api_key
    else:
        endpoint = settings.ocr_llm_vision_endpoint
        model = settings.ocr_llm_vision_model
        api_key = settings.ocr_llm_vision_api_key
    return _probe_openai_compatible_backend(
        name=f"ocr:{backend}",
        endpoint=endpoint,
        model=model,
        api_key=api_key,
    )


def _probe_llm_backend(settings: Settings) -> RemoteBackendStatus:
    kn_settings = get_knowledge_settings()
    if kn_settings.use_mock_llm:
        return RemoteBackendStatus(
            name="knowledge_llm",
            status="ok",
            endpoint=kn_settings.llm_endpoint,
            model=kn_settings.llm_model,
            detail="Mock LLM attivo.",
            server_reachable=True,
            model_available=True,
        )
    return _probe_openai_compatible_backend(
        name="knowledge_llm",
        endpoint=os.getenv("KN_WORKER_LLM_ENDPOINT", kn_settings.llm_endpoint),
        model=kn_settings.llm_model,
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
        models = payload.get("data", []) if isinstance(payload, dict) else []
        model_ids = {
            item.get("id")
            for item in models
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
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
        elif not server_reachable:
            detail = f"Model listing failed: HTTP {exc.code}"
    except URLError as exc:
        if not server_reachable:
            detail = f"Backend non raggiungibile: {exc.reason}"
    except Exception as exc:
        if not server_reachable:
            detail = f"Model listing failed: {exc}"

    status = "ok"
    if not server_reachable:
        status = "error"
    elif model_available is False:
        status = "degraded"

    if detail is None and status == "ok":
        detail = "Backend remoto operativo."

    return RemoteBackendStatus(
        name=name,
        status=status,
        endpoint=active_endpoint,
        model=model,
        detail=detail,
        server_reachable=server_reachable,
        model_available=model_available,
        latency_ms=latency_ms,
    )
