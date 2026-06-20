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
    ocr_backend: str | None = None


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
    is_stale: bool = False
    stale_reason: str | None = None


class DocumentResponse(BaseModel):
    id: UUID
    external_id: str | None
    original_filename: str
    mime_type: str
    sha256: str
    size_bytes: int
    source_type: str
    created_at: datetime
    scan_unit_count: int = 0
    document_unit_count: int = 0
    rotation_applied: int | None = None
    page_order_reversed: bool | None = None


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


class RemoteBackendStatus(BaseModel):
    name: str
    status: str
    endpoint: str | None = None
    model: str | None = None
    detail: str | None = None
    server_reachable: bool = False
    model_available: bool | None = None
    latency_ms: int | None = None


class SystemStatusResponse(BaseModel):
    status: str
    database: str
    redis: str
    storage: str
    ocr_backend: RemoteBackendStatus
    llm_backend: RemoteBackendStatus


class ManualCommentCreate(BaseModel):
    selected_text: str
    selection_start: int | None = None
    selection_end: int | None = None
    comment_text: str
    author_name: str | None = None


class ManualCommentResponse(BaseModel):
    id: UUID
    manual_slug: str
    selected_text: str
    selection_start: int | None
    selection_end: int | None
    comment_text: str
    author_name: str | None
    status: str
    resolution_note: str | None
    resolved_by: str | None
    resolved_at: datetime | None
    created_at: datetime


class ManualResponse(BaseModel):
    slug: str
    title: str
    markdown: str
    comments: list[ManualCommentResponse]


class ManualCommentUpdate(BaseModel):
    status: str
    resolution_note: str | None = None
    resolved_by: str | None = None
