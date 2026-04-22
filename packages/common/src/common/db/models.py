import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from common.db.base import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_sha256", "sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="document")
    jobs: Mapped[list["IngestionJob"]] = relationship(back_populates="document")
    assets: Mapped[list["DocumentAsset"]] = relationship(back_populates="document")
    ocr_results: Mapped[list["OCRResult"]] = relationship(back_populates="document")


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_doc_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped["Document"] = relationship(back_populates="versions")
    ocr_results: Mapped[list["OCRResult"]] = relationship(back_populates="document_version")


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        Index("ix_ingestion_jobs_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=5, server_default="5")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="jobs")


class OCRResult(Base):
    __tablename__ = "ocr_results"
    __table_args__ = (
        Index("ix_ocr_results_document_created_at", "document_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    engine_name: Mapped[str] = mapped_column(String(64), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(64), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    markdown_text: Mapped[str] = mapped_column(Text, nullable=False)
    structured_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped["Document"] = relationship(back_populates="ocr_results")
    document_version: Mapped["DocumentVersion"] = relationship(back_populates="ocr_results")


class DocumentAsset(Base):
    __tablename__ = "document_assets"
    __table_args__ = (
        Index("ix_document_assets_document_type", "document_id", "asset_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_object_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    document: Mapped["Document"] = relationship(back_populates="assets")
