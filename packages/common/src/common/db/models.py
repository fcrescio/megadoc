import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint, Uuid, func
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
    mentions: Mapped[list["DocumentUnitMention"]] = relationship(back_populates="document_unit", cascade="all, delete-orphan")
    assertions: Mapped[list["KnowledgeAssertion"]] = relationship(back_populates="document_unit", cascade="all, delete-orphan")
    topic_assignments: Mapped[list["DocumentUnitTopicAssignment"]] = relationship(
        back_populates="document_unit", cascade="all, delete-orphan"
    )
    specialist_jobs: Mapped[list["SpecialistJob"]] = relationship(
        back_populates="document_unit", cascade="all, delete-orphan"
    )
    specialist_results: Mapped[list["SpecialistResult"]] = relationship(
        back_populates="document_unit", cascade="all, delete-orphan"
    )
    context_memberships: Mapped[list["KnowledgeContextMembership"]] = relationship(
        back_populates="document_unit", cascade="all, delete-orphan"
    )
    accounting_facts: Mapped[list["AccountingFact"]] = relationship(
        back_populates="document_unit", cascade="all, delete-orphan"
    )
    outgoing_links: Mapped[list["DocumentUnitLink"]] = relationship(
        foreign_keys="DocumentUnitLink.source_document_unit_id",
        back_populates="source_document_unit",
        cascade="all, delete-orphan",
    )
    incoming_links: Mapped[list["DocumentUnitLink"]] = relationship(
        foreign_keys="DocumentUnitLink.target_document_unit_id",
        back_populates="target_document_unit",
        cascade="all, delete-orphan",
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


class SpecialistJob(Base):
    __tablename__ = "specialist_jobs"
    __table_args__ = (
        Index("ix_specialist_jobs_status_created_at", "status", "created_at"),
        Index("ix_specialist_jobs_unit_type", "document_unit_id", "specialist_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_units.id", ondelete="CASCADE"), nullable=False
    )
    specialist_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    input_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document_unit: Mapped["DocumentUnit"] = relationship(back_populates="specialist_jobs")


class SpecialistResult(Base):
    __tablename__ = "specialist_results"
    __table_args__ = (
        Index("ix_specialist_results_unit_type", "document_unit_id", "specialist_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_units.id", ondelete="CASCADE"), nullable=False
    )
    specialist_type: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto_accepted")
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document_unit: Mapped["DocumentUnit"] = relationship(back_populates="specialist_results")
    assertions: Mapped[list["KnowledgeAssertion"]] = relationship(back_populates="specialist_result")
    accounting_facts: Mapped[list["AccountingFact"]] = relationship(back_populates="specialist_result")


class DocumentUnitLink(Base):
    __tablename__ = "document_unit_links"
    __table_args__ = (
        Index("ix_document_unit_links_source_type", "source_document_unit_id", "link_type"),
        Index("ix_document_unit_links_target_type", "target_document_unit_id", "link_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_document_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_units.id", ondelete="CASCADE"), nullable=False
    )
    target_document_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_units.id", ondelete="CASCADE"), nullable=False
    )
    link_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    source_document_unit: Mapped["DocumentUnit"] = relationship(
        foreign_keys=[source_document_unit_id],
        back_populates="outgoing_links",
    )
    target_document_unit: Mapped["DocumentUnit"] = relationship(
        foreign_keys=[target_document_unit_id],
        back_populates="incoming_links",
    )


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
    primary_contexts: Mapped[list["KnowledgeContext"]] = relationship(back_populates="canonical_entity")
    context_anchors: Mapped[list["KnowledgeContextAnchor"]] = relationship(
        back_populates="canonical_entity", cascade="all, delete-orphan"
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


class KnowledgeContext(Base):
    __tablename__ = "knowledge_contexts"
    __table_args__ = (
        UniqueConstraint("context_kind", "canonical_entity_id", name="uq_knowledge_contexts_kind_entity"),
        Index("ix_knowledge_contexts_kind_label", "context_kind", "label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    context_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="entity")
    canonical_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    canonical_entity: Mapped["CanonicalEntity"] = relationship(back_populates="primary_contexts")
    anchors: Mapped[list["KnowledgeContextAnchor"]] = relationship(
        back_populates="context", cascade="all, delete-orphan"
    )
    memberships: Mapped[list["KnowledgeContextMembership"]] = relationship(
        back_populates="context", cascade="all, delete-orphan"
    )


class KnowledgeContextAnchor(Base):
    __tablename__ = "knowledge_context_anchors"
    __table_args__ = (
        UniqueConstraint("context_id", "canonical_entity_id", name="uq_knowledge_context_anchors_entity"),
        Index("ix_knowledge_context_anchors_entity", "canonical_entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    context_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_contexts.id", ondelete="CASCADE"), nullable=False
    )
    canonical_entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("canonical_entities.id", ondelete="CASCADE"), nullable=False
    )
    anchor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    context: Mapped["KnowledgeContext"] = relationship(back_populates="anchors")
    canonical_entity: Mapped["CanonicalEntity"] = relationship(back_populates="context_anchors")


class KnowledgeContextMembership(Base):
    __tablename__ = "knowledge_context_memberships"
    __table_args__ = (
        UniqueConstraint("context_id", "document_unit_id", name="uq_knowledge_context_memberships_unit"),
        Index("ix_knowledge_context_memberships_unit", "document_unit_id"),
        Index("ix_knowledge_context_memberships_context_role", "context_id", "membership_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    context_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_contexts.id", ondelete="CASCADE"), nullable=False
    )
    document_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_units.id", ondelete="CASCADE"), nullable=False
    )
    membership_role: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    context: Mapped["KnowledgeContext"] = relationship(back_populates="memberships")
    document_unit: Mapped["DocumentUnit"] = relationship(back_populates="context_memberships")


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"
    __table_args__ = (
        UniqueConstraint("node_kind", "canonical_key", name="uq_knowledge_nodes_kind_key"),
        Index("ix_knowledge_nodes_kind_label", "node_kind", "label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    node_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    canonical_key: Mapped[str] = mapped_column(String(512), nullable=False)
    label: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    aliases: Mapped[list["KnowledgeNodeAlias"]] = relationship(back_populates="node", cascade="all, delete-orphan")
    mentions: Mapped[list["DocumentUnitMention"]] = relationship(back_populates="node", cascade="all, delete-orphan")
    subject_assertions: Mapped[list["KnowledgeAssertion"]] = relationship(
        foreign_keys="KnowledgeAssertion.subject_node_id",
        back_populates="subject_node",
    )
    object_assertions: Mapped[list["KnowledgeAssertion"]] = relationship(
        foreign_keys="KnowledgeAssertion.object_node_id",
        back_populates="object_node",
    )
    accounting_accounts: Mapped[list["AccountingAccount"]] = relationship(back_populates="scope_node")


class KnowledgeNodeAlias(Base):
    __tablename__ = "knowledge_node_aliases"
    __table_args__ = (
        UniqueConstraint("node_id", "normalized_alias", name="uq_knowledge_node_aliases_node_alias"),
        Index("ix_knowledge_node_aliases_normalized", "normalized_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False)
    alias: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    node: Mapped["KnowledgeNode"] = relationship(back_populates="aliases")


class KnowledgePredicate(Base):
    __tablename__ = "knowledge_predicates"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    value_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_facetable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    assertions: Mapped[list["KnowledgeAssertion"]] = relationship(back_populates="predicate")


class AccountingAccount(Base):
    __tablename__ = "accounting_accounts"
    __table_args__ = (
        UniqueConstraint("scope_key", "account_key", name="uq_accounting_accounts_scope_key"),
        Index("ix_accounting_accounts_label_unit", "subject_label", "unit_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scope_node_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_nodes.id", ondelete="SET NULL"), nullable=True
    )
    scope_key: Mapped[str] = mapped_column(String(512), nullable=False)
    account_key: Mapped[str] = mapped_column(String(512), nullable=False)
    unit_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_label: Mapped[str] = mapped_column(String(512), nullable=False)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    scope_node: Mapped["KnowledgeNode | None"] = relationship(back_populates="accounting_accounts")
    aliases: Mapped[list["AccountingAccountAlias"]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )
    facts: Mapped[list["AccountingFact"]] = relationship(back_populates="account", cascade="all, delete-orphan")


class AccountingAccountAlias(Base):
    __tablename__ = "accounting_account_aliases"
    __table_args__ = (
        UniqueConstraint("account_id", "normalized_alias", name="uq_accounting_account_aliases_account_alias"),
        Index("ix_accounting_account_aliases_normalized", "normalized_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounting_accounts.id", ondelete="CASCADE"), nullable=False
    )
    alias: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(512), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    account: Mapped["AccountingAccount"] = relationship(back_populates="aliases")


class AccountingFact(Base):
    __tablename__ = "accounting_facts"
    __table_args__ = (
        Index("ix_accounting_facts_account_type", "account_id", "fact_type"),
        Index("ix_accounting_facts_unit_type", "document_unit_id", "fact_type"),
        Index("ix_accounting_facts_category", "category_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_units.id", ondelete="CASCADE"), nullable=False
    )
    specialist_result_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("specialist_results.id", ondelete="CASCADE"), nullable=True
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("accounting_accounts.id", ondelete="CASCADE"), nullable=False
    )
    accounting_role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    category_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    category_label: Mapped[str | None] = mapped_column(String(512), nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    raw_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    period_context_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_context_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    period_review_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_total: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document_unit: Mapped["DocumentUnit"] = relationship(back_populates="accounting_facts")
    specialist_result: Mapped["SpecialistResult | None"] = relationship(back_populates="accounting_facts")
    account: Mapped["AccountingAccount"] = relationship(back_populates="facts")


class DocumentUnitMention(Base):
    __tablename__ = "document_unit_mentions"
    __table_args__ = (
        Index("ix_document_unit_mentions_unit", "document_unit_id"),
        Index("ix_document_unit_mentions_node", "node_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_units.id", ondelete="CASCADE"), nullable=False
    )
    node_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("knowledge_nodes.id", ondelete="CASCADE"), nullable=False)
    mention_role: Mapped[str] = mapped_column(String(32), nullable=False, default="mentioned")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="entity")
    surface_text: Mapped[str] = mapped_column(String(512), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    page_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_to: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document_unit: Mapped["DocumentUnit"] = relationship(back_populates="mentions")
    node: Mapped["KnowledgeNode"] = relationship(back_populates="mentions")


class KnowledgeAssertion(Base):
    __tablename__ = "knowledge_assertions"
    __table_args__ = (
        Index("ix_knowledge_assertions_unit_predicate", "document_unit_id", "predicate_code"),
        Index("ix_knowledge_assertions_subject_predicate", "subject_node_id", "predicate_code"),
        Index("ix_knowledge_assertions_object_predicate", "object_node_id", "predicate_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_units.id", ondelete="CASCADE"), nullable=False
    )
    predicate_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("knowledge_predicates.code", ondelete="RESTRICT"), nullable=False
    )
    subject_node_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_nodes.id", ondelete="SET NULL"), nullable=True
    )
    object_node_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_nodes.id", ondelete="SET NULL"), nullable=True
    )
    value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON, nullable=True)
    value_text: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    specialist_result_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("specialist_results.id", ondelete="SET NULL"), nullable=True
    )
    evidence_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document_unit: Mapped["DocumentUnit"] = relationship(back_populates="assertions")
    predicate: Mapped["KnowledgePredicate"] = relationship(back_populates="assertions")
    subject_node: Mapped["KnowledgeNode | None"] = relationship(
        foreign_keys=[subject_node_id], back_populates="subject_assertions"
    )
    object_node: Mapped["KnowledgeNode | None"] = relationship(
        foreign_keys=[object_node_id], back_populates="object_assertions"
    )
    specialist_result: Mapped["SpecialistResult | None"] = relationship(back_populates="assertions")


class DocumentUnitTopicAssignment(Base):
    __tablename__ = "document_unit_topic_assignments"
    __table_args__ = (
        UniqueConstraint(
            "document_unit_id", "topic_id", "assignment_role",
            name="uq_document_unit_topic_assignments_unit_topic_role",
        ),
    )

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
