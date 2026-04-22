"""Pydantic schemas for knowledge classifier."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# Enums
class ScanUnitStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SEGMENTED = "segmented"
    CLASSIFIED = "classified"
    ASSIGNED = "assigned"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class DocumentUnitStatus(str, Enum):
    PENDING = "pending"
    SEGMENTED = "segmented"
    CLASSIFIED = "classified"
    ASSIGNED = "assigned"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class TopicProposalStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    MERGED_INTO_EXISTING = "merged_into_existing"


class ReviewStatus(str, Enum):
    AUTO_ACCEPTED = "auto_accepted"
    NEEDS_REVIEW = "needs_review"
    HUMAN_REVIEWED = "human_reviewed"
    CORRECTED = "corrected"


class AssignmentRole(str, Enum):
    PRIMARY = "primary"
    SECONDARY = "secondary"


class TopicClass(str, Enum):
    CASE_FILE = "case_file"
    MEETING = "meeting"
    FINANCIAL_PERIOD = "financial_period"
    VENDOR_RELATIONSHIP = "vendor_relationship"
    BUILDING_ISSUE = "building_issue"
    LEGAL_MATTER = "legal_matter"
    GENERAL_ADMINISTRATION = "general_administration"
    OTHER = "other"


class EntityTypes(str, Enum):
    PERSON = "person"
    ORGANIZATION = "organization"
    CONDOMINIUM = "condominio"
    ADDRESS = "indirizzo"
    VENDOR = "fornitore"
    DATE = "data"
    PERIOD = "periodo"
    AMOUNT = "importo"
    DOCUMENT_NUMBER = "numero_documento"


# Page representation
class PageRepresentation(BaseModel):
    """Representation of a single page from OCR."""
    page_number: int = Field(..., ge=1)
    text: str = Field(...)
    headings: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


# Segmentation
class SegmentBoundary(BaseModel):
    """A boundary between document segments."""
    page_before: int
    page_after: int
    confidence: float = Field(..., ge=0, le=1)
    rationale: str


class SegmentCandidate(BaseModel):
    """A candidate document segment."""
    start_page: int = Field(..., ge=1)
    end_page: int = Field(..., ge=1)
    confidence: float = Field(..., ge=0, le=1)
    rationale: str


class SegmentationResult(BaseModel):
    """Result of document segmentation."""
    segments: list[SegmentCandidate] = Field(...)
    overall_confidence: float = Field(..., ge=0, le=1)
    boundaries: list[SegmentBoundary] = Field(default_factory=list)


# Classification
class DocumentTypeCandidate(BaseModel):
    """A candidate document type classification."""
    type_code: str
    confidence: float = Field(..., ge=0, le=1)
    salient_features: list[str] = Field(default_factory=list)


class ClassificationResult(BaseModel):
    """Result of document type classification."""
    primary_type: DocumentTypeCandidate = Field(...)
    alternatives: list[DocumentTypeCandidate] = Field(default_factory=list)
    rationale: str


# Entity Extraction
class ExtractedEntity(BaseModel):
    """An extracted entity from a document."""
    entity_type: str
    entity_value: str
    normalized_value: str | None = None
    confidence: float = Field(..., ge=0, le=1)
    page_from: int | None = None
    page_to: int | None = None


class EntityExtractionResult(BaseModel):
    """Result of entity extraction."""
    entities: list[ExtractedEntity] = Field(...)
    summary: str | None = None


# Topic Retrieval
class TopicCandidate(BaseModel):
    """A candidate topic for assignment."""
    topic_id: str
    slug: str
    title: str
    score: float = Field(..., ge=0, le=1)
    reasons: list[str] = Field(default_factory=list)


class TopicRetrievalResult(BaseModel):
    """Result of topic candidate retrieval."""
    candidates: list[TopicCandidate] = Field(...)
    has_strong_match: bool


# Topic Assignment
class TopicAssignmentDecision(BaseModel):
    """Decision for topic assignment."""
    action: str  # assign_existing, assign_multiple, propose_new, needs_review
    topic_ids: list[str] = Field(default_factory=list)
    assignment_roles: list[str] = Field(default_factory=list)
    proposed_topic: dict[str, Any] | None = None
    confidence: float = Field(..., ge=0, le=1)
    rationale: str


# API Schemas
class ScanUnitCreate(BaseModel):
    """Request to create a scan unit from OCR result."""
    ocr_result_id: str


class ScanUnitResponse(BaseModel):
    """Response for scan unit."""
    id: str
    source_document_id: str
    source_ocr_result_id: str
    page_count: int
    status: str
    segmentation_confidence: float | None
    classification_confidence: float | None
    assignment_confidence: float | None
    created_at: datetime
    updated_at: datetime | None


class DocumentUnitResponse(BaseModel):
    """Response for document unit."""
    id: str
    scan_unit_id: str
    ordinal: int
    start_page: int
    end_page: int
    title: str | None
    document_type_code: str | None
    document_type_name: str | None
    document_type_confidence: float | None
    segmentation_confidence: float | None
    extracted_summary: str | None
    review_status: str
    entities: list[ExtractedEntity]
    topic_assignments: list["TopicAssignmentResponse"]
    proposal: "TopicProposalResponse" | None
    created_at: datetime
    updated_at: datetime | None


class TopicAssignmentResponse(BaseModel):
    """Response for topic assignment."""
    id: str
    topic_id: str
    topic_slug: str
    topic_title: str
    assignment_role: str
    confidence: float | None
    rationale: str | None


class TopicProposalResponse(BaseModel):
    """Response for topic proposal."""
    id: str
    proposed_slug: str
    proposed_title: str
    topic_class: str
    description: str | None
    proposal_status: str
    confidence: float | None
    rationale: str | None
    created_at: datetime
    reviewed_at: datetime | None


class TopicResponse(BaseModel):
    """Response for topic."""
    id: str
    slug: str
    title: str
    topic_class: str
    description: str | None
    canonical: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime | None


class TopicCreate(BaseModel):
    """Request to create a topic."""
    slug: str
    title: str
    topic_class: str
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)


class DocumentTypeResponse(BaseModel):
    """Response for document type."""
    id: str
    code: str
    name: str
    description: str | None
    parent_code: str | None
    is_active: bool
    created_at: datetime


class KnowledgeJobResponse(BaseModel):
    """Response for knowledge job."""
    id: str
    scan_unit_id: str
    job_type: str
    status: str
    attempt_count: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class ReviewUpdate(BaseModel):
    """Request to update review status."""
    document_type_code: str | None = None
    title: str | None = None
    review_status: str | None = None
