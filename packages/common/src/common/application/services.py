import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from sqlalchemy.orm import Session

from common.application.repositories import (
    DocumentRepository,
    DocumentVersionRepository,
    JobRepository,
    OCRResultRepository,
)
from common.config import Settings, get_settings
from common.db.models import Document, DocumentAsset, DocumentVersion, IngestionJob, OCRResult
from common.domain.enums import AssetType, JobStatus, JobType, OCRStatus, SourceType
from common.domain.exceptions import NotFoundError, ProcessingError, ValidationError
from common.domain.models import OCRResultModel
from common.infrastructure.security import sha256_file, validate_pdf_magic_bytes
from common.logging import get_logger
from common.processing.backends import DocumentProcessingBackend, get_processing_backend
from common.processing.orientation import OrientationPreprocessService
from common.processing.preflight import PDFPreflightReport, PDFPreflightService
from common.processing.refinement import OCRRefinementService
from common.storage.backends import StorageBackend, get_storage_backend

logger = get_logger(__name__)


@dataclass
class UploadResult:
    document: Document
    version: DocumentVersion
    deduplicated: bool


class DocumentService:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or get_storage_backend(self.settings)
        self.documents = DocumentRepository(session)
        self.versions = DocumentVersionRepository(session)

    def save_upload(
        self,
        source_path: Path,
        filename: str,
        source_type: SourceType,
        external_id: str | None = None,
    ) -> UploadResult:
        validate_pdf_magic_bytes(source_path)
        size_bytes = source_path.stat().st_size
        if size_bytes > self.settings.max_upload_size_bytes:
            raise ValidationError("File exceeds configured upload size limit.")
        sha256 = sha256_file(source_path)

        if external_id is not None:
            external_id = external_id.strip() or None

        existing = None
        if external_id is not None:
            existing = self.documents.find_by_external_id(external_id)
        elif self.settings.deduplicate_by_hash:
            existing = self.documents.find_by_sha256(sha256)

        if existing is not None and external_id is None and self.settings.deduplicate_by_hash:
            latest_version = self.versions.get_latest_for_document(existing.id)
            if latest_version is None:
                raise ValidationError("Existing document has no versions.")
            return UploadResult(document=existing, version=latest_version, deduplicated=True)

        if existing is None:
            document = Document(
                external_id=external_id,
                original_filename=filename,
                mime_type="application/pdf",
                sha256=sha256,
                size_bytes=size_bytes,
                source_type=source_type.value,
            )
            self.session.add(document)
            self.session.flush()
            version_number = 1
            deduplicated = False
        else:
            document = existing
            latest_version = self.versions.get_latest_for_document(document.id)
            if latest_version is None:
                raise ValidationError("Existing document has no versions.")

            if self.settings.deduplicate_by_hash and document.sha256 == sha256:
                return UploadResult(document=document, version=latest_version, deduplicated=True)

            version_number = latest_version.version_number + 1
            document.original_filename = filename
            document.mime_type = "application/pdf"
            document.sha256 = sha256
            document.size_bytes = size_bytes
            document.source_type = source_type.value
            deduplicated = False

        version = DocumentVersion(
            document_id=document.id,
            version_number=version_number,
            storage_bucket=self.settings.s3_bucket_raw,
            storage_object_key=f"{document.id}/v{version_number}/original.pdf",
        )
        self.session.add(version)
        self.session.flush()

        self.storage.put_file(
            source_path,
            bucket=version.storage_bucket,
            key=version.storage_object_key,
            content_type="application/pdf",
        )

        asset = DocumentAsset(
            document_id=document.id,
            asset_type=AssetType.ORIGINAL_PDF.value,
            storage_bucket=version.storage_bucket,
            storage_object_key=version.storage_object_key,
            content_type="application/pdf",
        )
        self.session.add(asset)
        self.session.commit()
        self.session.refresh(document)
        self.session.refresh(version)
        return UploadResult(document=document, version=version, deduplicated=deduplicated)


class JobService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.jobs = JobRepository(session)
        self.documents = DocumentRepository(session)

    def create_ingest_job(self, document_id: UUID, priority: int = 5) -> IngestionJob:
        document = self.documents.get(document_id)
        if document is None:
            raise NotFoundError(f"Document {document_id} not found.")

        existing = self.jobs.find_active_ingest_job(document_id)
        if existing is not None:
            return existing

        job = IngestionJob(
            document_id=document_id,
            job_type=JobType.INGEST.value,
            status=JobStatus.QUEUED.value,
            priority=priority,
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def mark_running(self, job: IngestionJob) -> None:
        job.status = JobStatus.RUNNING.value
        job.started_at = datetime.now(timezone.utc)
        job.attempt_count += 1
        self.session.commit()

    def mark_failed(self, job: IngestionJob, message: str) -> None:
        job.status = JobStatus.FAILED.value
        job.error_message = message
        job.finished_at = datetime.now(timezone.utc)
        self.session.commit()

    def mark_succeeded(self, job: IngestionJob) -> None:
        job.status = JobStatus.SUCCEEDED.value
        job.error_message = None
        job.finished_at = datetime.now(timezone.utc)
        self.session.commit()


class OCRService:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        storage: StorageBackend | None = None,
        processor: DocumentProcessingBackend | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or get_storage_backend(self.settings)
        self.processor = processor or get_processing_backend(self.settings)
        self.preflight = PDFPreflightService(self.settings)
        self.orientation = OrientationPreprocessService(self.settings)
        self.refinement = OCRRefinementService(self.settings)
        self.documents = DocumentRepository(session)
        self.versions = DocumentVersionRepository(session)
        self.results = OCRResultRepository(session)
        self.jobs = JobRepository(session)

    def process_job(self, job_id: UUID) -> OCRResult:
        job = self.jobs.get(job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found.")

        document = self.documents.get(job.document_id)
        if document is None:
            raise NotFoundError(f"Document {job.document_id} not found.")
        version = self.versions.get_latest_for_document(document.id)
        if version is None:
            raise NotFoundError(f"No version found for document {document.id}.")

        temp_path: Path | None = None
        normalized_path: Path | None = None
        try:
            with NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                temp_path = Path(tmp.name)
            self.storage.download_to_path(version.storage_bucket, version.storage_object_key, temp_path)
            preflight_report = self.preflight.analyze(temp_path)
            if not preflight_report.valid_pdf:
                raise ProcessingError(preflight_report.error or "PDF preflight failed.")
            orientation_result = self.orientation.preprocess(temp_path, preflight_report)
            processing_source = temp_path
            if orientation_result and orientation_result.normalized_path is not None:
                normalized_path = orientation_result.normalized_path
                processing_source = normalized_path
            ocr_result_model = self.processor.process(processing_source, preflight=preflight_report)
            ocr_result_model.structured_json = {
                **ocr_result_model.structured_json,
                "preflight": preflight_report.model_dump(mode="json"),
            }
            if orientation_result is not None:
                ocr_result_model.structured_json = {
                    **ocr_result_model.structured_json,
                    "orientation_preprocess": orientation_result.metadata,
                }
            ocr_result_model.confidence_summary = self._merge_confidence_summary(
                ocr_result_model.confidence_summary,
                preflight_report,
            )
            if orientation_result is not None:
                ocr_result_model.confidence_summary = self._merge_orientation_summary(
                    ocr_result_model.confidence_summary,
                    orientation_result.metadata,
                )
            refinement_payload = self.refinement.refine(temp_path, ocr_result_model, preflight_report)
            if refinement_payload is not None:
                ocr_result_model.refinement_payload = refinement_payload
                ocr_result_model.structured_json = {
                    **ocr_result_model.structured_json,
                    "ocr_refinement": refinement_payload.get("summary", {}),
                }
                ocr_result_model.confidence_summary = self._merge_refinement_summary(
                    ocr_result_model.confidence_summary,
                    refinement_payload,
                )
                if self.settings.ocr_refinement_promote_text:
                    refined_full_text = refinement_payload.get("refined_full_text")
                    if refined_full_text:
                        ocr_result_model.full_text = refined_full_text
                        ocr_result_model.markdown_text = refined_full_text
            return self._store_ocr_result(document.id, version.id, ocr_result_model)
        finally:
            if normalized_path is not None:
                normalized_path.unlink(missing_ok=True)
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _store_ocr_result(
        self, document_id: UUID, version_id: UUID, result_model: OCRResultModel
    ) -> OCRResult:
        base_key = f"{document_id}/{version_id}/ocr"
        self.storage.put_bytes(
            result_model.markdown_text.encode("utf-8"),
            bucket=self.settings.s3_bucket_derivatives,
            key=f"{base_key}/result.md",
            content_type="text/markdown",
        )
        self.storage.put_bytes(
            result_model.full_text.encode("utf-8"),
            bucket=self.settings.s3_bucket_derivatives,
            key=f"{base_key}/result.txt",
            content_type="text/plain",
        )
        json_bytes = result_model.model_dump_json(indent=2).encode("utf-8")
        self.storage.put_bytes(
            json_bytes,
            bucket=self.settings.s3_bucket_derivatives,
            key=f"{base_key}/result.json",
            content_type="application/json",
        )

        preflight_payload = None
        if isinstance(result_model.confidence_summary, dict):
            preflight_payload = result_model.confidence_summary.get("preflight")
        if preflight_payload is not None:
            self.storage.put_bytes(
                json.dumps(preflight_payload, indent=2).encode("utf-8"),
                bucket=self.settings.s3_bucket_derivatives,
                key=f"{base_key}/preflight.json",
                content_type="application/json",
            )
        if result_model.refinement_payload is not None:
            self.storage.put_bytes(
                json.dumps(result_model.refinement_payload, indent=2).encode("utf-8"),
                bucket=self.settings.s3_bucket_derivatives,
                key=f"{base_key}/ocr_refinement.json",
                content_type="application/json",
            )

        assets = [
            DocumentAsset(
                document_id=document_id,
                asset_type=AssetType.MARKDOWN.value,
                storage_bucket=self.settings.s3_bucket_derivatives,
                storage_object_key=f"{base_key}/result.md",
                content_type="text/markdown",
            ),
            DocumentAsset(
                document_id=document_id,
                asset_type=AssetType.TEXT.value,
                storage_bucket=self.settings.s3_bucket_derivatives,
                storage_object_key=f"{base_key}/result.txt",
                content_type="text/plain",
            ),
            DocumentAsset(
                document_id=document_id,
                asset_type=AssetType.OCR_JSON.value,
                storage_bucket=self.settings.s3_bucket_derivatives,
                storage_object_key=f"{base_key}/result.json",
                content_type="application/json",
            ),
        ]
        if preflight_payload is not None:
            assets.append(
                DocumentAsset(
                    document_id=document_id,
                    asset_type=AssetType.PREFLIGHT_JSON.value,
                    storage_bucket=self.settings.s3_bucket_derivatives,
                    storage_object_key=f"{base_key}/preflight.json",
                    content_type="application/json",
                )
            )
        if result_model.refinement_payload is not None:
            assets.append(
                DocumentAsset(
                    document_id=document_id,
                    asset_type=AssetType.OCR_REFINEMENT_JSON.value,
                    storage_bucket=self.settings.s3_bucket_derivatives,
                    storage_object_key=f"{base_key}/ocr_refinement.json",
                    content_type="application/json",
                )
            )

        self.session.add_all(assets)

        ocr_result = OCRResult(
            document_id=document_id,
            document_version_id=version_id,
            engine_name=result_model.engine_name,
            engine_version=result_model.engine_version,
            pipeline_version=result_model.pipeline_version,
            status=OCRStatus.SUCCEEDED.value,
            full_text=result_model.full_text,
            markdown_text=result_model.markdown_text,
            structured_json=result_model.structured_json,
            page_count=result_model.page_count,
            confidence_summary=result_model.confidence_summary,
        )
        self.session.add(ocr_result)
        self.session.commit()
        self.session.refresh(ocr_result)
        logger.info("ocr_result_stored", document_id=str(document_id), version_id=str(version_id))
        return ocr_result

    def _merge_confidence_summary(
        self,
        confidence_summary: dict | None,
        preflight_report: PDFPreflightReport,
    ) -> dict:
        merged = dict(confidence_summary or {})
        merged["preflight"] = preflight_report.model_dump(mode="json")
        return merged

    def _merge_refinement_summary(
        self,
        confidence_summary: dict | None,
        refinement_payload: dict,
    ) -> dict:
        merged = dict(confidence_summary or {})
        merged["ocr_refinement"] = refinement_payload.get("summary", {})
        return merged

    def _merge_orientation_summary(
        self,
        confidence_summary: dict | None,
        orientation_metadata: dict,
    ) -> dict:
        merged = dict(confidence_summary or {})
        merged["orientation_preprocess"] = orientation_metadata
        return merged


def persist_upload_to_temp(source, destination: Path) -> None:
    with destination.open("wb") as handle:
        shutil.copyfileobj(source, handle)
