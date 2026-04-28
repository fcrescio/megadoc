"""Knowledge classifier API router."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from common.db.models import (
    DocumentType,
    OCRResult,
    ScanUnit,
    DocumentUnit,
    DocumentUnitEntity,
    DocumentUnitTopicAssignment,
    Topic,
    TopicProposal,
    KnowledgeJob,
)
from common.db.session import SessionLocal, get_db_session
from knowledge_classifier.schemas import (
    ConsolidationResponse,
    ScanUnitCreate,
    ScanUnitResponse,
    DocumentUnitResponse,
    TopicResponse,
    TopicSummaryResponse,
    TopicDetailResponse,
    TopicRelatedDocumentResponse,
    TopicCreate,
    TopicProposalResponse,
    DocumentTypeResponse,
    KnowledgeJobResponse,
    ReviewUpdate,
    ReviewStatus,
    TopicAssignmentUpsert,
    TopicProposalResolution,
)
from knowledge_classifier.services.consolidation import KnowledgeBaseConsolidationService
from knowledge_worker.dispatch import dispatch_scan_unit_processing

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_entity(entity: DocumentUnitEntity) -> dict[str, Any]:
    return {
        "id": str(entity.id),
        "entity_type": entity.entity_type,
        "entity_value": entity.entity_value,
        "normalized_value": entity.normalized_value,
        "confidence": entity.confidence,
        "page_from": entity.page_from,
        "page_to": entity.page_to,
    }


def _serialize_topic_assignment(assignment: DocumentUnitTopicAssignment) -> dict[str, Any]:
    topic = assignment.topic
    return {
        "id": str(assignment.id),
        "topic_id": str(assignment.topic_id),
        "topic_slug": topic.slug if topic else None,
        "topic_title": topic.title if topic else None,
        "topic_kind": topic.topic_kind if topic else None,
        "topic_class": topic.topic_class if topic else None,
        "assignment_role": assignment.assignment_role,
        "confidence": assignment.confidence,
        "rationale": assignment.rationale,
    }


def _serialize_topic_proposal(proposal: TopicProposal | None) -> dict[str, Any] | None:
    if proposal is None:
        return None
    source_document_unit = proposal.source_document_unit
    source_scan_unit = source_document_unit.scan_unit if source_document_unit else None
    source_document = source_scan_unit.document if source_scan_unit else None
    return {
        "id": str(proposal.id),
        "proposed_slug": proposal.proposed_slug,
        "proposed_title": proposal.proposed_title,
        "topic_class": proposal.topic_class,
        "proposed_topic_kind": proposal.proposed_topic_kind,
        "description": proposal.description,
        "proposal_status": proposal.proposal_status,
        "matched_existing_topic_id": str(proposal.matched_existing_topic_id) if proposal.matched_existing_topic_id else None,
        "matched_existing_topic_title": proposal.matched_topic.title if proposal.matched_topic else None,
        "source_document_unit_id": str(source_document_unit.id) if source_document_unit else None,
        "source_document_id": str(source_document.id) if source_document else None,
        "source_document_filename": source_document.original_filename if source_document else None,
        "source_start_page": source_document_unit.start_page if source_document_unit else None,
        "source_end_page": source_document_unit.end_page if source_document_unit else None,
        "confidence": proposal.confidence,
        "rationale": proposal.rationale,
        "created_at": proposal.created_at,
        "reviewed_at": proposal.reviewed_at,
    }


def _serialize_document_unit(doc_unit: DocumentUnit) -> dict[str, Any]:
    return {
        "id": str(doc_unit.id),
        "scan_unit_id": str(doc_unit.scan_unit_id),
        "ordinal": doc_unit.ordinal,
        "start_page": doc_unit.start_page,
        "end_page": doc_unit.end_page,
        "title": doc_unit.title,
        "document_type_code": doc_unit.document_type.code if doc_unit.document_type else None,
        "document_type_name": doc_unit.document_type.name if doc_unit.document_type else None,
        "document_type_confidence": doc_unit.document_type_confidence,
        "segmentation_confidence": doc_unit.segmentation_confidence,
        "extracted_summary": doc_unit.extracted_summary,
        "review_status": doc_unit.review_status,
        "entities": [_serialize_entity(entity) for entity in doc_unit.entities],
        "topic_assignments": [
            _serialize_topic_assignment(assignment)
            for assignment in doc_unit.topic_assignments
        ],
        "proposal": _serialize_topic_proposal(doc_unit.proposal),
        "created_at": doc_unit.created_at,
        "updated_at": doc_unit.updated_at,
    }


def _serialize_topic_summary(topic: Topic) -> TopicSummaryResponse:
    related_document_ids = {
        str(assignment.document_unit.scan_unit.source_document_id)
        for assignment in topic.assignments
        if assignment.document_unit and assignment.document_unit.scan_unit
    }
    return TopicSummaryResponse(
        id=str(topic.id),
        slug=topic.slug,
        title=topic.title,
        topic_class=topic.topic_class,
        topic_kind=topic.topic_kind,
        description=topic.description,
        canonical=topic.canonical,
        is_active=topic.is_active,
        assignment_count=len(topic.assignments),
        proposal_count=sum(1 for proposal in topic.proposals if proposal.proposal_status == "proposed"),
        related_document_count=len(related_document_ids),
        alias_count=len(topic.aliases),
        created_at=topic.created_at,
        updated_at=topic.updated_at,
    )


def _serialize_topic_detail(topic: Topic) -> TopicDetailResponse:
    related_documents: list[TopicRelatedDocumentResponse] = []
    seen_units: set[str] = set()
    for assignment in sorted(
        topic.assignments,
        key=lambda item: (
            item.document_unit.scan_unit.document.created_at if item.document_unit and item.document_unit.scan_unit and item.document_unit.scan_unit.document else item.created_at,
            item.document_unit.ordinal if item.document_unit else 0,
        ),
        reverse=True,
    ):
        document_unit = assignment.document_unit
        if document_unit is None or document_unit.scan_unit is None or document_unit.scan_unit.document is None:
            continue
        unit_id = str(document_unit.id)
        if unit_id in seen_units:
            continue
        seen_units.add(unit_id)
        document = document_unit.scan_unit.document
        related_documents.append(
            TopicRelatedDocumentResponse(
                document_id=str(document.id),
                external_id=document.external_id,
                original_filename=document.original_filename,
                created_at=document.created_at,
                document_unit_id=unit_id,
                document_type_code=document_unit.document_type.code if document_unit.document_type else None,
                review_status=document_unit.review_status,
                topic_assignment_confidence=assignment.confidence,
                assignment_role=assignment.assignment_role,
                start_page=document_unit.start_page,
                end_page=document_unit.end_page,
                summary=document_unit.extracted_summary,
            )
        )

    return TopicDetailResponse(
        topic=_serialize_topic_summary(topic),
        aliases=sorted({alias.alias for alias in topic.aliases}),
        related_documents=related_documents,
    )


def _serialize_scan_unit(scan_unit: ScanUnit, include_units: bool = False) -> dict[str, Any]:
    payload = {
        "id": str(scan_unit.id),
        "source_document_id": str(scan_unit.source_document_id),
        "source_document_version_id": str(scan_unit.source_document_version_id)
        if scan_unit.source_document_version_id
        else None,
        "source_ocr_result_id": str(scan_unit.source_ocr_result_id),
        "page_count": scan_unit.page_count,
        "status": scan_unit.status,
        "segmentation_confidence": scan_unit.segmentation_confidence,
        "classification_confidence": scan_unit.classification_confidence,
        "assignment_confidence": scan_unit.assignment_confidence,
        "created_at": scan_unit.created_at,
        "updated_at": scan_unit.updated_at,
    }
    if include_units:
        payload["document_units"] = [
            _serialize_document_unit(doc_unit)
            for doc_unit in sorted(scan_unit.document_units, key=lambda unit: unit.ordinal)
        ]
    return payload


def _get_or_create_topic_from_payload(
    payload: TopicCreate,
    db: Session,
) -> Topic:
    existing = db.execute(select(Topic).where(Topic.slug == payload.slug)).scalar_one_or_none()
    if existing is not None:
        existing.title = payload.title
        existing.topic_class = payload.topic_class
        existing.topic_kind = payload.topic_kind
        existing.description = payload.description
        existing.canonical = True
        existing.is_active = True
        existing.updated_at = _utcnow()
        topic = existing
    else:
        topic = Topic(
            slug=payload.slug,
            title=payload.title,
            topic_class=payload.topic_class,
            topic_kind=payload.topic_kind,
            description=payload.description,
            canonical=True,
            is_active=True,
        )
        db.add(topic)
        db.flush()
    alias_values = {topic.slug.lower(), topic.title.lower()}
    alias_values.update(alias.alias.lower() for alias in topic.aliases)
    for candidate_alias in payload.aliases:
        if candidate_alias.lower() not in alias_values:
            db.add(TopicAlias(topic_id=topic.id, alias=candidate_alias))
            alias_values.add(candidate_alias.lower())
    return topic


def _assign_topic_to_document_unit(
    doc_unit: DocumentUnit,
    topic: Topic,
    assignment_role: str,
    db: Session,
    confidence: float | None = None,
    rationale: str | None = None,
) -> DocumentUnitTopicAssignment:
    existing = next(
        (
            assignment
            for assignment in doc_unit.topic_assignments
            if assignment.topic_id == topic.id and assignment.assignment_role == assignment_role
        ),
        None,
    )
    if existing is not None:
        existing.confidence = confidence if confidence is not None else existing.confidence
        existing.rationale = rationale or existing.rationale
        return existing
    assignment = DocumentUnitTopicAssignment(
        document_unit_id=doc_unit.id,
        topic_id=topic.id,
        assignment_role=assignment_role,
        confidence=confidence,
        rationale=rationale,
    )
    db.add(assignment)
    doc_unit.topic_assignments.append(assignment)
    return assignment


@router.get("/documents/{document_id}")
def get_document_knowledge(document_id: str, db: Session = Depends(get_db_session)):
    """Return scan units and rich document-unit results for a source document."""
    try:
        parsed_document_id = uuid.UUID(document_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid document ID") from exc

    result = db.execute(
        select(ScanUnit)
        .where(ScanUnit.source_document_id == parsed_document_id)
        .order_by(ScanUnit.created_at.desc())
    )
    scan_units = result.scalars().unique().all()
    return {
        "document_id": document_id,
        "scan_units": [
            _serialize_scan_unit(scan_unit, include_units=True)
            for scan_unit in scan_units
        ],
    }


# Scan Units
@router.post("/scan-units/from-ocr/{ocr_result_id}", response_model=ScanUnitResponse)
async def create_scan_unit_from_ocr(
    ocr_result_id: str,
    data: ScanUnitCreate,
    db: Session = Depends(get_db_session),
):
    """Create a scan unit from an OCR result and start processing."""
    # Verify OCR result exists
    result = db.execute(
        select(OCRResult).where(OCRResult.id == uuid.UUID(ocr_result_id))
    )
    ocr_result = result.scalar_one_or_none()
    if not ocr_result:
        raise HTTPException(status_code=404, detail="OCR result not found")
    
    # Create scan unit
    scan_unit = ScanUnit(
        source_document_id=ocr_result.document_id,
        source_document_version_id=ocr_result.document_version_id,
        source_ocr_result_id=ocr_result.id,
        page_count=ocr_result.page_count,
        status="pending",
    )
    db.add(scan_unit)
    db.flush()  # Get scan_unit.id
    
    # Create knowledge job
    job = KnowledgeJob(
        scan_unit_id=scan_unit.id,
        job_type="full_processing",
        status="pending",
    )
    db.add(job)
    
    # Queue the processing task
    dispatch_scan_unit_processing(str(scan_unit.id))
    
    # Update job status
    job.status = "queued"
    db.commit()
    
    return ScanUnitResponse(
        id=str(scan_unit.id),
        source_document_id=str(scan_unit.source_document_id),
        source_ocr_result_id=str(scan_unit.source_ocr_result_id),
        page_count=scan_unit.page_count,
        status=scan_unit.status,
        segmentation_confidence=scan_unit.segmentation_confidence,
        classification_confidence=scan_unit.classification_confidence,
        assignment_confidence=scan_unit.assignment_confidence,
        created_at=scan_unit.created_at,
        updated_at=scan_unit.updated_at,
    )


@router.get("/scan-units", response_model=list[ScanUnitResponse])
def list_scan_units(db: Session = Depends(get_db_session)):
    """List all scan units."""
    result = db.execute(select(ScanUnit).order_by(ScanUnit.created_at.desc()))
    scan_units = result.scalars().all()
    
    return [
        ScanUnitResponse(
            id=str(su.id),
            source_document_id=str(su.source_document_id),
            source_ocr_result_id=str(su.source_ocr_result_id),
            page_count=su.page_count,
            status=su.status,
            segmentation_confidence=su.segmentation_confidence,
            classification_confidence=su.classification_confidence,
            assignment_confidence=su.assignment_confidence,
            created_at=su.created_at,
            updated_at=su.updated_at,
        )
        for su in scan_units
    ]


@router.get("/scan-units/{scan_unit_id}", response_model=ScanUnitResponse)
def get_scan_unit(scan_unit_id: str, db: Session = Depends(get_db_session)):
    """Get a scan unit by ID."""
    result = db.execute(
        select(ScanUnit).where(ScanUnit.id == uuid.UUID(scan_unit_id))
    )
    scan_unit = result.scalar_one_or_none()
    if not scan_unit:
        raise HTTPException(status_code=404, detail="Scan unit not found")
    
    return ScanUnitResponse(
        id=str(scan_unit.id),
        source_document_id=str(scan_unit.source_document_id),
        source_ocr_result_id=str(scan_unit.source_ocr_result_id),
        page_count=scan_unit.page_count,
        status=scan_unit.status,
        segmentation_confidence=scan_unit.segmentation_confidence,
        classification_confidence=scan_unit.classification_confidence,
        assignment_confidence=scan_unit.assignment_confidence,
        created_at=scan_unit.created_at,
        updated_at=scan_unit.updated_at,
    )


# Document Units
@router.get("/scan-units/{scan_unit_id}/document-units", response_model=list[DocumentUnitResponse])
def list_document_units(scan_unit_id: str, db: Session = Depends(get_db_session)):
    """List document units for a scan unit."""
    result = db.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.proposal).selectinload(TopicProposal.matched_topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
        )
        .where(DocumentUnit.scan_unit_id == uuid.UUID(scan_unit_id))
        .order_by(DocumentUnit.ordinal)
    )
    doc_units = result.scalars().all()

    return [DocumentUnitResponse(**_serialize_document_unit(du)) for du in doc_units]


@router.get("/document-units/{document_unit_id}", response_model=DocumentUnitResponse)
def get_document_unit(document_unit_id: str, db: Session = Depends(get_db_session)):
    """Get a document unit by ID."""
    result = db.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.proposal).selectinload(TopicProposal.matched_topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
        )
        .where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if not doc_unit:
        raise HTTPException(status_code=404, detail="Document unit not found")

    return DocumentUnitResponse(**_serialize_document_unit(doc_unit))


@router.post("/document-units/{document_unit_id}/review", response_model=DocumentUnitResponse)
def review_document_unit(
    document_unit_id: str,
    update: ReviewUpdate,
    db: Session = Depends(get_db_session),
):
    """Update review status for a document unit."""
    result = db.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.proposal).selectinload(TopicProposal.matched_topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
        )
        .where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if not doc_unit:
        raise HTTPException(status_code=404, detail="Document unit not found")
    
    if update.review_status:
        doc_unit.review_status = update.review_status
    if update.title:
        doc_unit.title = update.title
    
    db.commit()

    return DocumentUnitResponse(**_serialize_document_unit(doc_unit))


@router.post("/document-units/{document_unit_id}/topic-assignments", response_model=DocumentUnitResponse)
def add_document_unit_topic_assignment(
    document_unit_id: str,
    payload: TopicAssignmentUpsert,
    db: Session = Depends(get_db_session),
):
    result = db.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.proposal).selectinload(TopicProposal.matched_topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
        )
        .where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if doc_unit is None:
        raise HTTPException(status_code=404, detail="Document unit not found")

    topic: Topic | None = None
    if payload.topic_id:
        topic = db.execute(select(Topic).where(Topic.id == uuid.UUID(payload.topic_id))).scalar_one_or_none()
        if topic is None:
            raise HTTPException(status_code=404, detail="Topic not found")
    elif payload.create_topic is not None:
        topic = _get_or_create_topic_from_payload(payload.create_topic, db)
    else:
        raise HTTPException(status_code=400, detail="Either topic_id or create_topic is required")

    _assign_topic_to_document_unit(
        doc_unit,
        topic,
        payload.assignment_role,
        db,
        confidence=payload.confidence,
        rationale=payload.rationale,
    )
    doc_unit.review_status = ReviewStatus.HUMAN_REVIEWED.value
    db.commit()
    db.refresh(doc_unit)
    return DocumentUnitResponse(**_serialize_document_unit(doc_unit))


@router.delete("/document-units/{document_unit_id}/topic-assignments/{assignment_id}", response_model=DocumentUnitResponse)
def delete_document_unit_topic_assignment(
    document_unit_id: str,
    assignment_id: str,
    db: Session = Depends(get_db_session),
):
    result = db.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(DocumentUnit.proposal).selectinload(TopicProposal.matched_topic),
            selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
        )
        .where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if doc_unit is None:
        raise HTTPException(status_code=404, detail="Document unit not found")

    assignment = next((item for item in doc_unit.topic_assignments if str(item.id) == assignment_id), None)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    db.delete(assignment)
    doc_unit.review_status = ReviewStatus.HUMAN_REVIEWED.value
    db.commit()
    db.refresh(doc_unit)
    return DocumentUnitResponse(**_serialize_document_unit(doc_unit))


# Topics
@router.get("/topics", response_model=list[TopicSummaryResponse])
def list_topics(
    include_inactive: bool = False,
    topic_kind: str | None = None,
    db: Session = Depends(get_db_session),
):
    """List topics with aggregate counts for knowledge-base browsing."""
    query = (
        select(Topic)
        .options(
            selectinload(Topic.aliases),
            selectinload(Topic.proposals),
            selectinload(Topic.assignments)
            .selectinload(DocumentUnitTopicAssignment.document_unit)
            .selectinload(DocumentUnit.scan_unit),
        )
        .order_by(Topic.created_at.desc())
    )
    if not include_inactive:
        query = query.where(Topic.is_active.is_(True))
    if topic_kind:
        query = query.where(Topic.topic_kind == topic_kind)

    topics = db.execute(query).scalars().unique().all()
    summaries = [_serialize_topic_summary(topic) for topic in topics]
    return sorted(
        summaries,
        key=lambda topic: (
            topic.assignment_count,
            topic.related_document_count,
            topic.proposal_count,
            topic.title.lower(),
        ),
        reverse=True,
    )


@router.get("/topics/{topic_id}", response_model=TopicDetailResponse)
def get_topic(topic_id: str, db: Session = Depends(get_db_session)):
    """Return a topic with aliases and related document units."""
    try:
        parsed_topic_id = uuid.UUID(topic_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid topic ID") from exc

    topic = db.execute(
        select(Topic)
        .options(
            selectinload(Topic.aliases),
            selectinload(Topic.proposals),
            selectinload(Topic.assignments)
            .selectinload(DocumentUnitTopicAssignment.document_unit)
            .selectinload(DocumentUnit.document_type),
            selectinload(Topic.assignments)
            .selectinload(DocumentUnitTopicAssignment.document_unit)
            .selectinload(DocumentUnit.scan_unit)
            .selectinload(ScanUnit.document),
        )
        .where(Topic.id == parsed_topic_id)
    ).scalar_one_or_none()
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return _serialize_topic_detail(topic)


@router.post("/topics", response_model=TopicResponse, status_code=status.HTTP_201_CREATED)
def create_topic(data: TopicCreate, db: Session = Depends(get_db_session)):
    """Create a new topic."""
    topic = _get_or_create_topic_from_payload(data, db)
    db.commit()
    
    return TopicResponse(
        id=str(topic.id),
        slug=topic.slug,
        title=topic.title,
        topic_class=topic.topic_class,
        topic_kind=topic.topic_kind,
        description=topic.description,
        canonical=topic.canonical,
        is_active=topic.is_active,
        created_at=topic.created_at,
        updated_at=topic.updated_at,
    )


@router.post("/consolidate/run-sync", response_model=ConsolidationResponse)
def run_consolidation_sync():
    """Merge semantically near-duplicate topics across the current knowledge base."""
    db = SessionLocal()
    try:
        service = KnowledgeBaseConsolidationService(db)
        stats = service.consolidate_topics()
        db.commit()
        return ConsolidationResponse(
            topics_before=stats.topics_before,
            topics_after=stats.topics_after,
            topics_merged=stats.topics_merged,
            aliases_created=stats.aliases_created,
            assignments_retargeted=stats.assignments_retargeted,
            proposals_retargeted=stats.proposals_retargeted,
        )
    finally:
        db.close()


# Topic Proposals
@router.get("/topic-proposals", response_model=list[TopicProposalResponse])
def list_topic_proposals(
    include_consolidated: bool = False,
    db: Session = Depends(get_db_session),
):
    """List topic proposals that need review."""
    statuses = ["proposed", "merged_into_existing"] if include_consolidated else ["proposed"]
    result = db.execute(
        select(TopicProposal)
        .options(
            selectinload(TopicProposal.source_document_unit)
            .selectinload(DocumentUnit.scan_unit)
            .selectinload(ScanUnit.document),
            selectinload(TopicProposal.matched_topic),
        )
        .where(TopicProposal.proposal_status.in_(statuses))
        .order_by(TopicProposal.created_at.desc())
    )
    proposals = result.scalars().all()

    return [TopicProposalResponse(**_serialize_topic_proposal(p)) for p in proposals]


@router.post("/topic-proposals/{proposal_id}/approve", response_model=DocumentUnitResponse)
def approve_topic_proposal(
    proposal_id: str,
    resolution: TopicProposalResolution | None = None,
    db: Session = Depends(get_db_session),
):
    """Resolve a topic proposal by creating or merging topics and assignments."""
    result = db.execute(
        select(TopicProposal)
        .options(
            selectinload(TopicProposal.matched_topic),
            selectinload(TopicProposal.source_document_unit).selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            selectinload(TopicProposal.source_document_unit).selectinload(DocumentUnit.document_type),
            selectinload(TopicProposal.source_document_unit).selectinload(DocumentUnit.entities),
            selectinload(TopicProposal.source_document_unit).selectinload(DocumentUnit.scan_unit).selectinload(ScanUnit.document),
        )
        .where(TopicProposal.id == uuid.UUID(proposal_id))
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.proposal_status != "proposed":
        raise HTTPException(status_code=409, detail="Only pending proposals can be approved")

    if resolution is None:
        resolution = TopicProposalResolution(
            action="merge_into_existing" if proposal.matched_existing_topic_id else "approve_new_topic",
            assignment_role="subject",
        )

    if resolution.action in {"merge_into_existing", "add_secondary_topic"}:
        target_topic_id = resolution.target_topic_id or (
            str(proposal.matched_existing_topic_id) if proposal.matched_existing_topic_id else None
        )
        if target_topic_id is None:
            raise HTTPException(status_code=400, detail="target_topic_id is required")
        topic = db.execute(select(Topic).where(Topic.id == uuid.UUID(target_topic_id))).scalar_one_or_none()
        if topic is None:
            raise HTTPException(status_code=404, detail="Target topic not found")
        topic.canonical = True
        topic.is_active = True
        topic.updated_at = _utcnow()
    else:
        create_topic_payload = resolution.create_topic or TopicCreate(
            slug=proposal.proposed_slug,
            title=proposal.proposed_title,
            topic_class=proposal.topic_class,
            topic_kind=proposal.proposed_topic_kind,
            description=proposal.description,
            aliases=[],
        )
        topic = _get_or_create_topic_from_payload(create_topic_payload, db)

    if proposal.source_document_unit is not None:
        if resolution.action == "merge_into_existing":
            provisional_assignments = [
                assignment
                for assignment in proposal.source_document_unit.topic_assignments
                if assignment.topic_id == proposal.matched_existing_topic_id
                or (
                    assignment.assignment_role == "primary"
                    and (assignment.topic is None or not assignment.topic.is_active or not assignment.topic.canonical)
                )
            ]
            if provisional_assignments:
                primary_assignment = provisional_assignments[0]
                primary_assignment.topic_id = topic.id
                primary_assignment.assignment_role = resolution.assignment_role
                primary_assignment.confidence = proposal.confidence
                primary_assignment.rationale = proposal.rationale
                for duplicate_assignment in provisional_assignments[1:]:
                    db.delete(duplicate_assignment)
            else:
                _assign_topic_to_document_unit(
                    proposal.source_document_unit,
                    topic,
                    resolution.assignment_role,
                    db,
                    confidence=proposal.confidence,
                    rationale=proposal.rationale,
                )
        else:
            _assign_topic_to_document_unit(
                proposal.source_document_unit,
                topic,
                resolution.assignment_role,
                db,
                confidence=proposal.confidence,
                rationale=proposal.rationale,
            )
        proposal.source_document_unit.review_status = ReviewStatus.HUMAN_REVIEWED.value

    proposal.proposal_status = "approved"
    proposal.matched_existing_topic_id = topic.id
    proposal.reviewed_at = _utcnow()

    db.commit()
    if proposal.source_document_unit is None:
        raise HTTPException(status_code=409, detail="Proposal has no source document unit")
    db.refresh(proposal.source_document_unit)
    return DocumentUnitResponse(**_serialize_document_unit(proposal.source_document_unit))


@router.post("/topic-proposals/{proposal_id}/reject", response_model=TopicProposalResponse)
def reject_topic_proposal(proposal_id: str, db: Session = Depends(get_db_session)):
    """Reject a topic proposal."""
    result = db.execute(
        select(TopicProposal)
        .options(
            selectinload(TopicProposal.matched_topic).selectinload(Topic.assignments),
            selectinload(TopicProposal.source_document_unit).selectinload(DocumentUnit.topic_assignments),
        )
        .where(TopicProposal.id == uuid.UUID(proposal_id))
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")

    if proposal.proposal_status != "proposed":
        raise HTTPException(status_code=409, detail="Only pending proposals can be rejected")

    if proposal.source_document_unit is not None:
        removable_assignments = [
            assignment
            for assignment in proposal.source_document_unit.topic_assignments
            if assignment.topic_id == proposal.matched_existing_topic_id
        ]
        for assignment in removable_assignments:
            db.delete(assignment)
        proposal.source_document_unit.review_status = ReviewStatus.HUMAN_REVIEWED.value

    provisional_topic = proposal.matched_topic
    provisional_topic_id = provisional_topic.id if provisional_topic is not None else None
    proposal.proposal_status = "rejected"
    proposal.reviewed_at = _utcnow()
    db.flush()

    if provisional_topic is not None and provisional_topic_id is not None:
        has_assignments = db.execute(
            select(DocumentUnitTopicAssignment).where(
                DocumentUnitTopicAssignment.topic_id == provisional_topic_id
            )
        ).first() is not None
        has_pending_proposals = db.execute(
            select(TopicProposal).where(
                TopicProposal.matched_existing_topic_id == provisional_topic_id,
                TopicProposal.proposal_status == "proposed",
            )
        ).first() is not None
        if not provisional_topic.is_active and not provisional_topic.canonical and not has_assignments and not has_pending_proposals:
            db.delete(provisional_topic)

    db.commit()

    return TopicProposalResponse(**_serialize_topic_proposal(proposal))


# Document Types
@router.get("/document-types", response_model=list[DocumentTypeResponse])
def list_document_types(db: Session = Depends(get_db_session)):
    """List all document types."""
    result = db.execute(select(DocumentType).order_by(DocumentType.code))
    types = result.scalars().all()
    
    return [
        DocumentTypeResponse(
            id=str(dt.id),
            code=dt.code,
            name=dt.name,
            description=dt.description,
            parent_code=dt.parent_code,
            is_active=dt.is_active,
            created_at=dt.created_at,
        )
        for dt in types
    ]


# Jobs
@router.get("/jobs/{job_id}", response_model=KnowledgeJobResponse)
def get_job(job_id: str, db: Session = Depends(get_db_session)):
    """Get a knowledge job by ID."""
    result = db.execute(
        select(KnowledgeJob).where(KnowledgeJob.id == uuid.UUID(job_id))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return KnowledgeJobResponse(
        id=str(job.id),
        scan_unit_id=str(job.scan_unit_id),
        job_type=job.job_type,
        status=job.status,
        attempt_count=job.attempt_count,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post("/jobs/{job_id}/run-sync")
def run_job_sync(job_id: str, db: Session = Depends(get_db_session)):
    """Run a job synchronously (for testing)."""
    import asyncio
    
    result = db.execute(
        select(KnowledgeJob).where(KnowledgeJob.id == uuid.UUID(job_id))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job.status = "running"
    db.flush()
    
    try:
        # For now, just mark as completed - full pipeline requires async session
        job.status = "completed"
        db.commit()
        return {"status": "completed", "message": "Sync execution not fully implemented"}
    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))
    
    return {"status": job.status, "result": result}
