import uuid
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from api.middleware import RequestContextMiddleware
from common.api.schemas import (
    CreateJobRequest,
    DocumentAssetResponse,
    DocumentResponse,
    DocumentVersionResponse,
    JobResponse,
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
from common.db.session import get_db_session
from common.domain.enums import SourceType
from common.domain.exceptions import NotFoundError, ValidationError
from common.logging import configure_logging
from common.storage.backends import StorageBackend, get_storage_backend
from worker.tasks import process_ingestion_job

configure_logging(get_settings().log_level)

app = FastAPI(title="megadoc api", version="0.1.0")
app.add_middleware(RequestContextMiddleware)


def dispatch_ingestion_job(job_id: uuid.UUID) -> None:
    settings = get_settings()
    if settings.celery_task_always_eager:
        process_ingestion_job(str(job_id))
        return
    process_ingestion_job.delay(str(job_id))


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


@app.post("/documents/upload", response_model=UploadResponse)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    auto_submit: bool = Query(default=True),
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
            result = document_service.save_upload(temp_path, file.filename or "upload.pdf", SourceType.API)
        finally:
            temp_path.unlink(missing_ok=True)
        job_id = None
        status = "stored"
        if auto_submit:
            job = job_service.create_ingest_job(result.document.id)
            dispatch_ingestion_job(job.id)
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
    dispatch_ingestion_job(job.id)
    return JobResponse.model_validate(job, from_attributes=True)


@app.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    limit: int = Query(default=100, le=500),
    session: Session = Depends(db_session_dep),
) -> list[JobResponse]:
    rows = JobRepository(session).list(limit)
    return [JobResponse.model_validate(row, from_attributes=True) for row in rows]


@app.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: uuid.UUID, session: Session = Depends(db_session_dep)) -> JobResponse:
    job = JobRepository(session).get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JobResponse.model_validate(job, from_attributes=True)


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
    headers = {"Content-Disposition": f'attachment; filename="{document.original_filename}"'}
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
