"""Knowledge classifier API router."""

import uuid
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
)
from knowledge_classifier.services.consolidation import KnowledgeBaseConsolidationService
from knowledge_worker.dispatch import dispatch_scan_unit_processing

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


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
        "topic_class": topic.topic_class if topic else None,
        "assignment_role": assignment.assignment_role,
        "confidence": assignment.confidence,
        "rationale": assignment.rationale,
    }


def _serialize_topic_proposal(proposal: TopicProposal | None) -> dict[str, Any] | None:
    if proposal is None:
        return None
    return {
        "id": str(proposal.id),
        "proposed_slug": proposal.proposed_slug,
        "proposed_title": proposal.proposed_title,
        "topic_class": proposal.topic_class,
        "description": proposal.description,
        "proposal_status": proposal.proposal_status,
        "matched_existing_topic_id": str(proposal.matched_existing_topic_id) if proposal.matched_existing_topic_id else None,
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
        description=topic.description,
        canonical=topic.canonical,
        is_active=topic.is_active,
        assignment_count=len(topic.assignments),
        proposal_count=len(topic.proposals),
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
        .where(DocumentUnit.scan_unit_id == uuid.UUID(scan_unit_id))
        .order_by(DocumentUnit.ordinal)
    )
    doc_units = result.scalars().all()
    
    return [
        DocumentUnitResponse(
            id=str(du.id),
            scan_unit_id=str(du.scan_unit_id),
            ordinal=du.ordinal,
            start_page=du.start_page,
            end_page=du.end_page,
            title=du.title,
            document_type_code=du.document_type.code if du.document_type else None,
            document_type_name=du.document_type.name if du.document_type else None,
            document_type_confidence=du.document_type_confidence,
            segmentation_confidence=du.segmentation_confidence,
            extracted_summary=du.extracted_summary,
            review_status=du.review_status,
            entities=[],  # Simplified
            topic_assignments=[],  # Simplified
            proposal=None,
            created_at=du.created_at,
            updated_at=du.updated_at,
        )
        for du in doc_units
    ]


@router.get("/document-units/{document_unit_id}", response_model=DocumentUnitResponse)
def get_document_unit(document_unit_id: str, db: Session = Depends(get_db_session)):
    """Get a document unit by ID."""
    result = db.execute(
        select(DocumentUnit).where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if not doc_unit:
        raise HTTPException(status_code=404, detail="Document unit not found")
    
    # Simplified response
    return DocumentUnitResponse(
        id=str(doc_unit.id),
        scan_unit_id=str(doc_unit.scan_unit_id),
        ordinal=doc_unit.ordinal,
        start_page=doc_unit.start_page,
        end_page=doc_unit.end_page,
        title=doc_unit.title,
        document_type_code=doc_unit.document_type.code if doc_unit.document_type else None,
        document_type_name=doc_unit.document_type.name if doc_unit.document_type else None,
        document_type_confidence=doc_unit.document_type_confidence,
        segmentation_confidence=doc_unit.segmentation_confidence,
        extracted_summary=doc_unit.extracted_summary,
        review_status=doc_unit.review_status,
        entities=[],
        topic_assignments=[],
        proposal=None,
        created_at=doc_unit.created_at,
        updated_at=doc_unit.updated_at,
    )


@router.post("/document-units/{document_unit_id}/review", response_model=DocumentUnitResponse)
def review_document_unit(
    document_unit_id: str,
    update: ReviewUpdate,
    db: Session = Depends(get_db_session),
):
    """Update review status for a document unit."""
    result = db.execute(
        select(DocumentUnit).where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if not doc_unit:
        raise HTTPException(status_code=404, detail="Document unit not found")
    
    if update.review_status:
        doc_unit.review_status = update.review_status
    if update.title:
        doc_unit.title = update.title
    
    db.commit()
    
    return DocumentUnitResponse(
        id=str(doc_unit.id),
        scan_unit_id=str(doc_unit.scan_unit_id),
        ordinal=doc_unit.ordinal,
        start_page=doc_unit.start_page,
        end_page=doc_unit.end_page,
        title=doc_unit.title,
        document_type_code=doc_unit.document_type.code if doc_unit.document_type else None,
        document_type_name=doc_unit.document_type.name if doc_unit.document_type else None,
        document_type_confidence=doc_unit.document_type_confidence,
        segmentation_confidence=doc_unit.segmentation_confidence,
        extracted_summary=doc_unit.extracted_summary,
        review_status=doc_unit.review_status,
        entities=[],
        topic_assignments=[],
        proposal=None,
        created_at=doc_unit.created_at,
        updated_at=doc_unit.updated_at,
    )


# Topics
@router.get("/topics", response_model=list[TopicSummaryResponse])
def list_topics(
    include_inactive: bool = False,
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
    topic = Topic(
        slug=data.slug,
        title=data.title,
        topic_class=data.topic_class,
        description=data.description,
        canonical=True,
        is_active=True,
    )
    db.add(topic)
    db.commit()
    
    return TopicResponse(
        id=str(topic.id),
        slug=topic.slug,
        title=topic.title,
        topic_class=topic.topic_class,
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
def list_topic_proposals(db: Session = Depends(get_db_session)):
    """List topic proposals."""
    result = db.execute(
        select(TopicProposal).where(TopicProposal.proposal_status == "proposed")
    )
    proposals = result.scalars().all()
    
    return [
        TopicProposalResponse(
            id=str(p.id),
            proposed_slug=p.proposed_slug,
            proposed_title=p.proposed_title,
            topic_class=p.topic_class,
            description=p.description,
            proposal_status=p.proposal_status,
            confidence=p.confidence,
            rationale=p.rationale,
            created_at=p.created_at,
            reviewed_at=p.reviewed_at,
        )
        for p in proposals
    ]


@router.post("/topic-proposals/{proposal_id}/approve", response_model=TopicResponse)
def approve_topic_proposal(proposal_id: str, db: Session = Depends(get_db_session)):
    """Approve a topic proposal and create the topic."""
    result = db.execute(
        select(TopicProposal).where(TopicProposal.id == uuid.UUID(proposal_id))
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    
    # Create the topic
    topic = Topic(
        slug=proposal.proposed_slug,
        title=proposal.proposed_title,
        topic_class=proposal.topic_class,
        description=proposal.description,
        canonical=True,
        is_active=True,
    )
    db.add(topic)
    
    # Update proposal
    proposal.proposal_status = "approved"
    proposal.matched_existing_topic_id = topic.id
    proposal.reviewed_at = topic.created_at
    
    db.commit()
    
    return TopicResponse(
        id=str(topic.id),
        slug=topic.slug,
        title=topic.title,
        topic_class=topic.topic_class,
        description=topic.description,
        canonical=topic.canonical,
        is_active=topic.is_active,
        created_at=topic.created_at,
        updated_at=topic.updated_at,
    )


@router.post("/topic-proposals/{proposal_id}/reject", response_model=TopicProposalResponse)
def reject_topic_proposal(proposal_id: str, db: Session = Depends(get_db_session)):
    """Reject a topic proposal."""
    result = db.execute(
        select(TopicProposal).where(TopicProposal.id == uuid.UUID(proposal_id))
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    
    proposal.proposal_status = "rejected"
    proposal.reviewed_at = proposal.created_at  # Simplified
    
    db.commit()
    
    return TopicProposalResponse(
        id=str(proposal.id),
        proposed_slug=proposal.proposed_slug,
        proposed_title=proposal.proposed_title,
        topic_class=proposal.topic_class,
        description=proposal.description,
        proposal_status=proposal.proposal_status,
        confidence=proposal.confidence,
        rationale=proposal.rationale,
        created_at=proposal.created_at,
        reviewed_at=proposal.reviewed_at,
    )


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
