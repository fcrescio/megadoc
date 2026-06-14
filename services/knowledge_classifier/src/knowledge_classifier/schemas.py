"""Pydantic schemas for knowledge classifier."""

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional

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
    SUBJECT = "subject"
    DOCUMENT_FAMILY = "document_family"
    CASE_OR_ISSUE = "case_or_issue"
    PERSON_OR_ORG_CONTEXT = "person_or_org_context"


class TopicKind(str, Enum):
    ENTITY = "entity"
    FAMILY = "family"
    ISSUE = "issue"
    PROJECT = "project"
    CONTEXT = "context"


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
    PERSON = "persona"
    ORGANIZATION = "organizzazione"
    ADDRESS = "indirizzo"
    PLACE = "luogo"


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
    entity_type: Literal[
        "organizzazione",
        "persona",
        "indirizzo",
        "luogo",
    ]
    entity_value: str = Field(..., max_length=256)
    normalized_value: Optional[str] = Field(default=None, max_length=256)
    confidence: float = Field(..., ge=0, le=1)
    page_from: Optional[int] = None
    page_to: Optional[int] = None


class EntityExtractionResult(BaseModel):
    """Result of entity extraction."""
    entities: list[ExtractedEntity] = Field(..., max_length=25)
    summary: Optional[str] = Field(default=None, max_length=500)


# Topic Retrieval
class TopicCandidate(BaseModel):
    """A candidate topic for assignment."""
    topic_id: str
    slug: str
    title: str
    topic_kind: Optional[str] = None
    assignment_count: int = 0
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
    proposal_action: Optional[str] = Field(
        default=None,
        description=(
            "Recommended action for the proposal: "
            "'create_topic' when a new stable topic/matter is needed, "
            "'attach_to_context' when the document fits an existing context without needing its own topic, "
            "'attach_to_existing_topic' when it matches an existing topic, "
            "'needs_review' when uncertain. "
            "Use 'attach_to_context' for single bills, invoices, payments that don't need their own topic."
        ),
    )
    confidence: float = Field(..., ge=0, le=1)
    rationale: str


# API Schemas - define in order to avoid forward reference issues
class TopicAssignmentResponse(BaseModel):
    """Response for topic assignment."""
    id: str
    topic_id: str
    topic_slug: str
    topic_title: str
    topic_kind: Optional[str] = None
    topic_class: Optional[str] = None
    assignment_role: str
    confidence: Optional[float] = None
    rationale: Optional[str] = None


class TopicProposalResponse(BaseModel):
    """Response for topic proposal."""
    id: str
    proposed_slug: str
    proposed_title: str
    topic_class: str
    proposed_topic_kind: str = TopicKind.ENTITY.value
    description: Optional[str] = None
    proposal_status: str
    matched_existing_topic_id: Optional[str] = None
    matched_existing_topic_title: Optional[str] = None
    source_document_unit_id: Optional[str] = None
    source_document_id: Optional[str] = None
    source_document_filename: Optional[str] = None
    source_start_page: Optional[int] = None
    source_end_page: Optional[int] = None
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    review_payload_json: Optional[dict[str, Any]] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None


class TopicSummaryResponse(BaseModel):
    id: str
    slug: str
    title: str
    topic_class: str
    topic_kind: str = TopicKind.ENTITY.value
    description: Optional[str] = None
    canonical: bool
    is_active: bool
    assignment_count: int
    proposal_count: int
    related_document_count: int
    alias_count: int
    created_at: datetime
    updated_at: Optional[datetime] = None


class TopicRelatedDocumentResponse(BaseModel):
    document_id: str
    external_id: Optional[str] = None
    original_filename: str
    created_at: datetime
    document_unit_id: str
    document_type_code: Optional[str] = None
    review_status: str
    topic_assignment_confidence: Optional[float] = None
    assignment_role: str
    start_page: int
    end_page: int
    summary: Optional[str] = None


class TopicDetailResponse(BaseModel):
    topic: TopicSummaryResponse
    aliases: list[str] = Field(default_factory=list)
    related_documents: list[TopicRelatedDocumentResponse] = Field(default_factory=list)


class KnowledgeSearchTopicHit(BaseModel):
    topic: TopicSummaryResponse
    aliases: list[str] = Field(default_factory=list)
    matched_fields: list[str] = Field(default_factory=list)


class KnowledgeSearchDocumentHit(BaseModel):
    document_unit_id: str
    document_id: str
    original_filename: str
    external_id: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    start_page: int
    end_page: int
    review_status: str
    document_type_code: Optional[str] = None
    topic_titles: list[str] = Field(default_factory=list)
    topic_kinds: list[str] = Field(default_factory=list)
    matched_fields: list[str] = Field(default_factory=list)


class KnowledgeSearchResponse(BaseModel):
    query: str
    total_topic_hits: int
    total_document_hits: int
    topics: list[KnowledgeSearchTopicHit] = Field(default_factory=list)
    document_units: list[KnowledgeSearchDocumentHit] = Field(default_factory=list)


class KnowledgeEntitySummaryResponse(BaseModel):
    entity_type: str
    entity_key: str
    display_value: str
    mention_count: int
    document_count: int
    topic_count: int


class KnowledgeEntityDocumentHitResponse(BaseModel):
    document_id: str
    document_unit_id: str
    original_filename: str
    external_id: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    review_status: str
    start_page: int
    end_page: int
    topic_titles: list[str] = Field(default_factory=list)


class KnowledgeEntityDetailResponse(BaseModel):
    entity_type: str
    entity_key: str
    display_value: str
    mention_count: int
    document_count: int
    topic_count: int
    documents: list[KnowledgeEntityDocumentHitResponse] = Field(default_factory=list)


class CanonicalEntitySummaryResponse(BaseModel):
    id: str
    entity_type: str
    canonical_value: str
    display_value: str
    review_status: str
    variant_count: int
    document_count: int


class CanonicalEntityVariantResponse(BaseModel):
    id: str
    entity_type: str
    entity_key: str
    display_value: str
    review_status: str


class CanonicalEntityDetailResponse(BaseModel):
    entity: CanonicalEntitySummaryResponse
    variants: list[CanonicalEntityVariantResponse] = Field(default_factory=list)
    documents: list[KnowledgeEntityDocumentHitResponse] = Field(default_factory=list)


class KnowledgeContextSummaryResponse(BaseModel):
    id: str
    context_kind: str
    label: str
    review_status: str
    canonical_entity_id: str
    canonical_entity_type: str
    canonical_value: str
    anchor_count: int
    document_count: int
    document_unit_count: int
    direct_membership_count: int


class KnowledgeContextMembershipResponse(BaseModel):
    document: KnowledgeEntityDocumentHitResponse
    membership_role: str
    confidence: Optional[float] = None
    source_type: str
    evidence_json: dict[str, Any] | None = None


class KnowledgeContextAnchorResponse(BaseModel):
    canonical_entity_id: str
    entity_type: str
    canonical_value: str
    display_value: str
    anchor_role: str


class KnowledgeContextDetailResponse(BaseModel):
    context: KnowledgeContextSummaryResponse
    anchors: list[KnowledgeContextAnchorResponse] = Field(default_factory=list)
    memberships: list[KnowledgeContextMembershipResponse] = Field(default_factory=list)


class KnowledgeContextStatsResponse(BaseModel):
    contexts: int
    memberships: int


class ContextAccountingPeriodAvailabilityResponse(BaseModel):
    accounting_role: str
    period_from: date
    period_to: date


class ContextAccountingSubjectResponse(BaseModel):
    account_key: str
    subject_label: str
    aliases: list[str] = Field(default_factory=list)
    unit_codes: list[str] = Field(default_factory=list)
    source_account_ids: list[str] = Field(default_factory=list)
    fact_count: int
    available_periods: list[ContextAccountingPeriodAvailabilityResponse] = Field(default_factory=list)


class ContextAccountingSourceResponse(BaseModel):
    fact_id: str
    specialist_result_id: Optional[str] = None
    document_unit_id: str
    original_filename: Optional[str] = None
    start_page: Optional[int] = None
    end_page: Optional[int] = None
    category_key: Optional[str] = None
    category_label: Optional[str] = None
    amount: float
    is_total: bool
    review_status: str
    evidence_json: dict[str, Any] | None = None


class ContextAccountingCategoryResponse(BaseModel):
    category_key: str
    category_label: str
    amount: float
    sources: list[ContextAccountingSourceResponse] = Field(default_factory=list)


class ContextAccountingPeriodBreakdownResponse(BaseModel):
    period_from: date
    period_to: date
    accounting_role: str
    validation_status: str
    total: Optional[float] = None
    component_total: Optional[float] = None
    reported_total: Optional[float] = None
    total_sources: list[ContextAccountingSourceResponse] = Field(default_factory=list)
    fact_count: int
    categories: list[ContextAccountingCategoryResponse] = Field(default_factory=list)


class ContextAccountingCategoryChangeResponse(BaseModel):
    category_key: str
    category_label: str
    amount_a: float
    amount_b: float
    delta: float
    percentage_change: Optional[float] = None
    sources_a: list[ContextAccountingSourceResponse] = Field(default_factory=list)
    sources_b: list[ContextAccountingSourceResponse] = Field(default_factory=list)


class ContextAccountingComparisonResponse(BaseModel):
    context_id: str
    requested_subject: str
    accounting_role: str
    status: str
    warnings: list[str] = Field(default_factory=list)
    candidates: list[ContextAccountingSubjectResponse] = Field(default_factory=list)
    selected_subject: ContextAccountingSubjectResponse | None = None
    period_a: ContextAccountingPeriodBreakdownResponse | None = None
    period_b: ContextAccountingPeriodBreakdownResponse | None = None
    direction: Optional[str] = None
    delta: Optional[float] = None
    percentage_change: Optional[float] = None
    changed_categories: list[ContextAccountingCategoryChangeResponse] = Field(default_factory=list)


class AccountingFactCorrectionRequest(BaseModel):
    corrected_amount: Optional[float] = None
    corrected_category_label: Optional[str] = None
    corrected_is_total: Optional[bool] = None
    excluded: Optional[bool] = None
    note: Optional[str] = None
    acted_by: Optional[str] = None


class AccountingFactCorrectionResponse(BaseModel):
    specialist_result_id: str
    document_unit_id: str
    review_status: str
    correction: dict[str, Any]


class CanonicalEntityCreate(BaseModel):
    entity_type: str
    canonical_value: str
    display_value: str


class CanonicalEntityMergeRequest(BaseModel):
    entity_type: str
    entity_keys: list[str] = Field(default_factory=list)
    target_canonical_entity_id: str | None = None
    create_canonical_entity: CanonicalEntityCreate | None = None


class KnowledgeGraphStatsResponse(BaseModel):
    document_units: int
    nodes: int
    mentions: int
    assertions: int


class KnowledgeNodeSummaryResponse(BaseModel):
    id: str
    node_kind: str
    canonical_key: str
    label: str
    description: Optional[str] = None
    review_status: str
    alias_count: int
    document_count: int
    assertion_count: int


class KnowledgeAssertionResponse(BaseModel):
    id: str
    document_unit_id: str
    predicate_code: str
    predicate_label: str
    value_kind: str
    object_node_id: Optional[str] = None
    object_node_label: Optional[str] = None
    value_json: Any = None
    value_text: Optional[str] = None
    confidence: Optional[float] = None
    review_status: str
    source_type: str


class KnowledgeNodeDetailResponse(BaseModel):
    node: KnowledgeNodeSummaryResponse
    aliases: list[str] = Field(default_factory=list)
    documents: list[KnowledgeEntityDocumentHitResponse] = Field(default_factory=list)
    assertions: list[KnowledgeAssertionResponse] = Field(default_factory=list)


class ConsolidationResponse(BaseModel):
    topics_before: int
    topics_after: int
    topics_merged: int
    aliases_created: int
    assignments_retargeted: int
    proposals_retargeted: int


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
    specialist_jobs: list[dict[str, Any]] = Field(default_factory=list)
    specialist_results: list[dict[str, Any]] = Field(default_factory=list)
    outgoing_links: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None


class TopicResponse(BaseModel):
    """Response for topic."""
    id: str
    slug: str
    title: str
    topic_class: str
    topic_kind: str = TopicKind.ENTITY.value
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
    topic_kind: str = TopicKind.ENTITY.value
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


class TopicAssignmentUpsert(BaseModel):
    topic_id: Optional[str] = None
    assignment_role: str = AssignmentRole.SECONDARY.value
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    create_topic: Optional[TopicCreate] = None


class TopicProposalResolution(BaseModel):
    action: Literal["approve_new_topic", "merge_into_existing", "add_secondary_topic", "reject"] = "merge_into_existing"
    assignment_role: str = AssignmentRole.SECONDARY.value
    target_topic_id: Optional[str] = None
    create_topic: Optional[TopicCreate] = None


class GraphSuggestionTopicSummaryResponse(BaseModel):
    id: str
    title: str
    slug: str
    topic_kind: str
    topic_class: str
    assignment_count: int
    dominant_assignment_role: str


class GraphMergeSuggestionResponse(BaseModel):
    axis: str
    score: float
    rationale: str
    shared_entity_keys: list[str] = Field(default_factory=list)
    shared_document_count: int
    source_topic: GraphSuggestionTopicSummaryResponse
    target_topic: GraphSuggestionTopicSummaryResponse


class GraphConsolidationSuggestionsResponse(BaseModel):
    subject: list[GraphMergeSuggestionResponse] = Field(default_factory=list)
    document_family: list[GraphMergeSuggestionResponse] = Field(default_factory=list)
    case_or_issue: list[GraphMergeSuggestionResponse] = Field(default_factory=list)


class GraphConsolidationReviewRequest(BaseModel):
    axis: Literal["subject", "document_family", "case_or_issue"]
    source_topic_id: str
    target_topic_id: str
    action: Literal[
        "merge_into_target",
        "dismiss",
        "mark_same_subject_different_family",
        "convert_to_secondary_relationship",
    ]
    note: Optional[str] = None
    acted_by: Optional[str] = None


class GraphConsolidationReviewResponse(BaseModel):
    status: str
    action: str
    source_topic_id: str
    target_topic_id: str
    affected_assignments: int = 0
