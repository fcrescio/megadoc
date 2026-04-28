import uuid
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from redis import Redis
from sqlalchemy import text
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
    ReadinessResponse,
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
from common.db.models import ManualComment
from common.db.schema import ensure_knowledge_schema
from common.db.session import engine, get_db_session
from common.domain.enums import SourceType
from common.domain.exceptions import NotFoundError, ValidationError
from common.logging import configure_logging
from common.storage.backends import StorageBackend, get_storage_backend
from worker.tasks import process_ingestion_job

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
    return [DocumentResponse.model_validate(row, from_attributes=True) for row in rows]


@app.get("/documents/{document_id}", response_model=DocumentResponse)
def get_document(document_id: uuid.UUID, session: Session = Depends(db_session_dep)) -> DocumentResponse:
    document = DocumentRepository(session).get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return DocumentResponse.model_validate(document, from_attributes=True)


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
