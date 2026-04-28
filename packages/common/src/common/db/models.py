import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, Uuid, func
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
    scan_units: Mapped[list["ScanUnit"]] = relationship(back_populates="document")


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
    scan_units: Mapped[list["ScanUnit"]] = relationship(back_populates="document_version")


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
    scan_units: Mapped[list["ScanUnit"]] = relationship(back_populates="ocr_result")


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


# Knowledge Classifier Models


class DocumentType(Base):
    __tablename__ = "document_types"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document_units: Mapped[list["DocumentUnit"]] = relationship(back_populates="document_type")


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (Index("ix_topics_class", "topic_class"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    topic_class: Mapped[str] = mapped_column(String(64), nullable=False)
    topic_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="entity")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    aliases: Mapped[list["TopicAlias"]] = relationship(back_populates="topic", cascade="all, delete-orphan")
    assignments: Mapped[list["DocumentUnitTopicAssignment"]] = relationship(back_populates="topic")
    proposals: Mapped[list["TopicProposal"]] = relationship(
        foreign_keys="TopicProposal.matched_existing_topic_id", back_populates="matched_topic"
    )
    outgoing_graph_reviews: Mapped[list["GraphConsolidationReview"]] = relationship(
        foreign_keys="GraphConsolidationReview.source_topic_id",
        back_populates="source_topic",
    )
    incoming_graph_reviews: Mapped[list["GraphConsolidationReview"]] = relationship(
        foreign_keys="GraphConsolidationReview.target_topic_id",
        back_populates="target_topic",
    )


class TopicAlias(Base):
    __tablename__ = "topic_aliases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    topic: Mapped["Topic"] = relationship(back_populates="aliases")


class TopicProposal(Base):
    __tablename__ = "topic_proposals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    proposed_slug: Mapped[str] = mapped_column(String(255), nullable=False)
    proposed_title: Mapped[str] = mapped_column(String(512), nullable=False)
    topic_class: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_topic_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="entity")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    proposal_status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_document_unit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("document_units.id", ondelete="SET NULL"), nullable=True)
    matched_existing_topic_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("topics.id"), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    source_document_unit: Mapped["DocumentUnit | None"] = relationship(
        primaryjoin="TopicProposal.source_document_unit_id == DocumentUnit.id",
        back_populates="proposal"
    )
    matched_topic: Mapped["Topic | None"] = relationship(
        primaryjoin="TopicProposal.matched_existing_topic_id == Topic.id"
    )


class ScanUnit(Base):
    __tablename__ = "scan_units"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_document_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    source_document_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True)
    source_ocr_result_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ocr_results.id", ondelete="CASCADE"), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    segmentation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    assignment_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped["Document"] = relationship(back_populates="scan_units")
    document_version: Mapped["DocumentVersion | None"] = relationship(back_populates="scan_units")
    ocr_result: Mapped["OCRResult"] = relationship(back_populates="scan_units")
    document_units: Mapped[list["DocumentUnit"]] = relationship(back_populates="scan_unit", cascade="all, delete-orphan")
    jobs: Mapped[list["KnowledgeJob"]] = relationship(back_populates="scan_unit", cascade="all, delete-orphan")
    llm_decisions: Mapped[list["LLMDecision"]] = relationship(back_populates="scan_unit")


class DocumentUnit(Base):
    __tablename__ = "document_units"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scan_unit_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("scan_units.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    document_type_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("document_types.id", ondelete="SET NULL"), nullable=True)
    document_type_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    segmentation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extracted_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scan_unit: Mapped["ScanUnit"] = relationship(back_populates="document_units")
    document_type: Mapped["DocumentType | None"] = relationship(back_populates="document_units")
    entities: Mapped[list["DocumentUnitEntity"]] = relationship(back_populates="document_unit", cascade="all, delete-orphan")
    topic_assignments: Mapped[list["DocumentUnitTopicAssignment"]] = relationship(
        back_populates="document_unit", cascade="all, delete-orphan"
    )
    proposal: Mapped["TopicProposal | None"] = relationship(
        foreign_keys="TopicProposal.source_document_unit_id", back_populates="source_document_unit", uselist=False
    )
    llm_decisions: Mapped[list["LLMDecision"]] = relationship(back_populates="document_unit")


class DocumentUnitEntity(Base):
    __tablename__ = "document_unit_entities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_unit_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("document_units.id", ondelete="CASCADE"), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_value: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document_unit: Mapped["DocumentUnit"] = relationship(back_populates="entities")


class CanonicalEntity(Base):
    __tablename__ = "canonical_entities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_value: Mapped[str] = mapped_column(String(512), nullable=False)
    display_value: Mapped[str] = mapped_column(String(512), nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    variants: Mapped[list["CanonicalEntityVariant"]] = relationship(
        back_populates="canonical_entity",
        cascade="all, delete-orphan",
    )


class CanonicalEntityVariant(Base):
    __tablename__ = "canonical_entity_variants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    canonical_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("canonical_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_key: Mapped[str] = mapped_column(String(512), nullable=False)
    display_value: Mapped[str] = mapped_column(String(512), nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    canonical_entity: Mapped["CanonicalEntity"] = relationship(back_populates="variants")


class DocumentUnitTopicAssignment(Base):
    __tablename__ = "document_unit_topic_assignments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_unit_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("document_units.id", ondelete="CASCADE"), nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    assignment_role: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document_unit: Mapped["DocumentUnit"] = relationship(back_populates="topic_assignments")
    topic: Mapped["Topic"] = relationship(back_populates="assignments")


class KnowledgeJob(Base):
    __tablename__ = "knowledge_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scan_unit_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("scan_units.id", ondelete="CASCADE"), nullable=False)
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scan_unit: Mapped["ScanUnit"] = relationship(back_populates="jobs")


class LLMDecision(Base):
    __tablename__ = "llm_decisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scan_unit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("scan_units.id", ondelete="SET NULL"), nullable=True)
    document_unit_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("document_units.id", ondelete="SET NULL"), nullable=True)
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    output_payload_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    scan_unit: Mapped["ScanUnit | None"] = relationship(back_populates="llm_decisions")
    document_unit: Mapped["DocumentUnit | None"] = relationship(back_populates="llm_decisions")


class ManualComment(Base):
    __tablename__ = "manual_comments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    manual_slug: Mapped[str] = mapped_column(String(128), nullable=False)
    selected_text: Mapped[str] = mapped_column(Text, nullable=False)
    selection_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selection_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_text: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", server_default="open")
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GraphConsolidationReview(Base):
    __tablename__ = "graph_consolidation_reviews"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    axis: Mapped[str] = mapped_column(String(32), nullable=False)
    source_topic_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    target_topic_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("topics.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    acted_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    source_topic: Mapped["Topic"] = relationship(
        foreign_keys=[source_topic_id],
        back_populates="outgoing_graph_reviews",
    )
    target_topic: Mapped["Topic"] = relationship(
        foreign_keys=[target_topic_id],
        back_populates="incoming_graph_reviews",
    )
