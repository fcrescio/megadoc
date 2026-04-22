"""Knowledge classifier API router."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession, select

from common.db.models import (
    DocumentType,
    OCRResult,
    ScanUnit,
    DocumentUnit,
    Topic,
    TopicProposal,
    KnowledgeJob,
)
from common.db.session import get_db
from knowledge_classifier.schemas import (
    ScanUnitCreate,
    ScanUnitResponse,
    DocumentUnitResponse,
    TopicResponse,
    TopicCreate,
    TopicProposalResponse,
    DocumentTypeResponse,
    KnowledgeJobResponse,
    ReviewUpdate,
)
from knowledge_worker.tasks import process_scan_unit_task

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


# Scan Units
@router.post("/scan-units/from-ocr/{ocr_result_id}", response_model=ScanUnitResponse)
async def create_scan_unit_from_ocr(
    ocr_result_id: str,
    data: ScanUnitCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a scan unit from an OCR result and start processing."""
    # Verify OCR result exists
    result = await db.execute(
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
    
    # Create knowledge job
    job = KnowledgeJob(
        scan_unit_id=scan_unit.id,
        job_type="full_processing",
        status="pending",
    )
    db.add(job)
    await db.flush()
    
    # Queue the processing task
    process_scan_unit_task.delay(str(scan_unit.id))
    
    # Update job status
    job.status = "queued"
    await db.commit()
    
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
async def list_scan_units(db: AsyncSession = Depends(get_db)):
    """List all scan units."""
    result = await db.execute(select(ScanUnit).order_by(ScanUnit.created_at.desc()))
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
async def get_scan_unit(scan_unit_id: str, db: AsyncSession = Depends(get_db)):
    """Get a scan unit by ID."""
    result = await db.execute(
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
async def list_document_units(scan_unit_id: str, db: AsyncSession = Depends(get_db)):
    """List document units for a scan unit."""
    result = await db.execute(
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
async def get_document_unit(document_unit_id: str, db: AsyncSession = Depends(get_db)):
    """Get a document unit by ID."""
    result = await db.execute(
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
async def review_document_unit(
    document_unit_id: str,
    update: ReviewUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update review status for a document unit."""
    result = await db.execute(
        select(DocumentUnit).where(DocumentUnit.id == uuid.UUID(document_unit_id))
    )
    doc_unit = result.scalar_one_or_none()
    if not doc_unit:
        raise HTTPException(status_code=404, detail="Document unit not found")
    
    if update.review_status:
        doc_unit.review_status = update.review_status
    if update.title:
        doc_unit.title = update.title
    
    await db.commit()
    
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
@router.get("/topics", response_model=list[TopicResponse])
async def list_topics(db: AsyncSession = Depends(get_db)):
    """List all topics."""
    result = await db.execute(select(Topic).where(Topic.is_active == True))
    topics = result.scalars().all()
    
    return [
        TopicResponse(
            id=str(t.id),
            slug=t.slug,
            title=t.title,
            topic_class=t.topic_class,
            description=t.description,
            canonical=t.canonical,
            is_active=t.is_active,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in topics
    ]


@router.post("/topics", response_model=TopicResponse, status_code=status.HTTP_201_CREATED)
async def create_topic(data: TopicCreate, db: AsyncSession = Depends(get_db)):
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
    await db.commit()
    
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


# Topic Proposals
@router.get("/topic-proposals", response_model=list[TopicProposalResponse])
async def list_topic_proposals(db: AsyncSession = Depends(get_db)):
    """List topic proposals."""
    result = await db.execute(
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
async def approve_topic_proposal(proposal_id: str, db: AsyncSession = Depends(get_db)):
    """Approve a topic proposal and create the topic."""
    result = await db.execute(
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
    
    await db.commit()
    
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
async def reject_topic_proposal(proposal_id: str, db: AsyncSession = Depends(get_db)):
    """Reject a topic proposal."""
    result = await db.execute(
        select(TopicProposal).where(TopicProposal.id == uuid.UUID(proposal_id))
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal not found")
    
    proposal.proposal_status = "rejected"
    proposal.reviewed_at = proposal.created_at  # Simplified
    
    await db.commit()
    
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
async def list_document_types(db: AsyncSession = Depends(get_db)):
    """List all document types."""
    result = await db.execute(select(DocumentType).order_by(DocumentType.code))
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
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get a knowledge job by ID."""
    result = await db.execute(
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
async def run_job_sync(job_id: str, db: AsyncSession = Depends(get_db)):
    """Run a job synchronously (for testing)."""
    result = await db.execute(
        select(KnowledgeJob).where(KnowledgeJob.id == uuid.UUID(job_id))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Import here to avoid circular imports
    from knowledge_classifier.llm.mock import MockDeterministicProvider
    from knowledge_classifier.services.pipeline import KnowledgePipelineService
    
    job.status = "running"
    await db.flush()
    
    try:
        llm = MockDeterministicProvider()
        pipeline = KnowledgePipelineService(llm, db)
        result = await pipeline.process_scan_unit(str(job.scan_unit_id))
        job.status = "completed"
    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        raise HTTPException(status_code=500, detail=str(e))
    
    await db.commit()
    
    return {"status": job.status, "result": result}
