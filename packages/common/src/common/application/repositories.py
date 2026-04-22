from typing import Iterable
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from common.db.models import Document, DocumentAsset, DocumentVersion, IngestionJob, OCRResult
from common.domain.enums import JobStatus, JobType


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, document_id: UUID) -> Document | None:
        return self.session.get(Document, document_id)

    def find_by_sha256(self, sha256: str) -> Document | None:
        return self.session.scalar(select(Document).where(Document.sha256 == sha256))

    def list(self, limit: int = 100) -> Iterable[Document]:
        stmt = select(Document).order_by(desc(Document.created_at)).limit(limit)
        return self.session.scalars(stmt).all()


class DocumentVersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_latest_for_document(self, document_id: UUID) -> DocumentVersion | None:
        stmt = (
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(desc(DocumentVersion.version_number))
            .limit(1)
        )
        return self.session.scalar(stmt)


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, job_id: UUID) -> IngestionJob | None:
        return self.session.get(IngestionJob, job_id)

    def list(self, limit: int = 100) -> Iterable[IngestionJob]:
        stmt = select(IngestionJob).order_by(desc(IngestionJob.created_at)).limit(limit)
        return self.session.scalars(stmt).all()

    def find_active_ingest_job(self, document_id: UUID) -> IngestionJob | None:
        stmt = select(IngestionJob).where(
            IngestionJob.document_id == document_id,
            IngestionJob.job_type == JobType.INGEST.value,
            IngestionJob.status.in_([JobStatus.QUEUED.value, JobStatus.RUNNING.value]),
        )
        return self.session.scalar(stmt)


class OCRResultRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_latest_for_document(self, document_id: UUID) -> OCRResult | None:
        stmt = (
            select(OCRResult)
            .where(OCRResult.document_id == document_id)
            .order_by(desc(OCRResult.created_at))
            .limit(1)
        )
        return self.session.scalar(stmt)


class AssetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_document(self, document_id: UUID) -> Iterable[DocumentAsset]:
        stmt = select(DocumentAsset).where(DocumentAsset.document_id == document_id)
        return self.session.scalars(stmt).all()

