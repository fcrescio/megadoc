"""Pydantic schemas for knowledge classifier."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

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
    normalized_value: Optional[str] = None
    confidence: float = Field(..., ge=0, le=1)
    page_from: Optional[int] = None
    page_to: Optional[int] = None


class EntityExtractionResult(BaseModel):
    """Result of entity extraction."""
    entities: list[ExtractedEntity] = Field(...)
    summary: Optional[str] = None


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
    proposed_topic: Optional[dict[str, Any]] = None
    confidence: float = Field(..., ge=0, le=1)
    rationale: str


# API Schemas - define in order to avoid forward reference issues
class TopicAssignmentResponse(BaseModel):
    """Response for topic assignment."""
    id: str
    topic_id: str
    topic_slug: str
    topic_title: str
    assignment_role: str
    confidence: Optional[float] = None
    rationale: Optional[str] = None


class TopicProposalResponse(BaseModel):
    """Response for topic proposal."""
    id: str
    proposed_slug: str
    proposed_title: str
    topic_class: str
    description: Optional[str] = None
    proposal_status: str
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None


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
    segmentation_confidence: Optional[float] = None
    classification_confidence: Optional[float] = None
    assignment_confidence: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class DocumentUnitResponse(BaseModel):
    """Response for document unit."""
    id: str
    scan_unit_id: str
    ordinal: int
    start_page: int
    end_page: int
    title: Optional[str] = None
    document_type_code: Optional[str] = None
    document_type_name: Optional[str] = None
    document_type_confidence: Optional[float] = None
    segmentation_confidence: Optional[float] = None
    extracted_summary: Optional[str] = None
    review_status: str
    entities: list[ExtractedEntity] = Field(default_factory=list)
    topic_assignments: list[TopicAssignmentResponse] = Field(default_factory=list)
    proposal: Optional[TopicProposalResponse] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class TopicResponse(BaseModel):
    """Response for topic."""
    id: str
    slug: str
    title: str
    topic_class: str
    description: Optional[str] = None
    canonical: bool
    is_active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None


class TopicCreate(BaseModel):
    """Request to create a topic."""
    slug: str
    title: str
    topic_class: str
    description: Optional[str] = None
    aliases: list[str] = Field(default_factory=list)


class DocumentTypeResponse(BaseModel):
    """Response for document type."""
    id: str
    code: str
    name: str
    description: Optional[str] = None
    parent_code: Optional[str] = None
    is_active: bool
    created_at: datetime


class KnowledgeJobResponse(BaseModel):
    """Response for knowledge job."""
    id: str
    scan_unit_id: str
    job_type: str
    status: str
    attempt_count: int
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class ReviewUpdate(BaseModel):
    """Request to update review status."""
    document_type_code: Optional[str] = None
    title: Optional[str] = None
    review_status: Optional[str] = None
