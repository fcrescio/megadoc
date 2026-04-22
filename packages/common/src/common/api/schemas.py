from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class UploadResponse(BaseModel):
    document_id: UUID
    version_id: UUID
    status: str
    deduplicated: bool = False
    job_id: UUID | None = None
    sha256: str
    size_bytes: int


class CreateJobRequest(BaseModel):
    document_id: UUID
    priority: int = 5


class JobResponse(BaseModel):
    id: UUID
    document_id: UUID
    job_type: str
    status: str
    priority: int
    attempt_count: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class DocumentResponse(BaseModel):
    id: UUID
    external_id: str | None
    original_filename: str
    mime_type: str
    sha256: str
    size_bytes: int
    source_type: str
    created_at: datetime


class DocumentVersionResponse(BaseModel):
    id: UUID
    document_id: UUID
    version_number: int
    storage_bucket: str
    storage_object_key: str
    created_at: datetime


class DocumentAssetResponse(BaseModel):
    id: UUID
    document_id: UUID
    asset_type: str
    storage_bucket: str
    storage_object_key: str
    content_type: str
    created_at: datetime


class OCRResponse(BaseModel):
    id: UUID
    document_id: UUID
    document_version_id: UUID
    engine_name: str
    engine_version: str
    pipeline_version: str
    status: str
    full_text: str
    markdown_text: str
    structured_json: dict
    page_count: int
    confidence_summary: dict | None
    created_at: datetime


class ReadinessResponse(BaseModel):
    status: str
    database: str
    redis: str
    storage: str
