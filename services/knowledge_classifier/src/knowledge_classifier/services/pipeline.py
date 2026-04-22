"""Knowledge pipeline service - orchestrates the full classification pipeline."""

import logging
import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from common.db.models import (
    DocumentUnit as DBDocumentUnit,
    DocumentUnitEntity as DBDocumentUnitEntity,
    DocumentUnitTopicAssignment as DBDocumentUnitTopicAssignment,
    DocumentType as DBDocumentType,
    LLMDecision,
    OCRResult,
    ScanUnit as DBScanUnit,
    Topic as DBTopic,
    TopicProposal,
)
from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.base import LLMProvider
from knowledge_classifier.schemas import (
    ReviewStatus,
    ScanUnitStatus,
    TopicProposalStatus,
)
from knowledge_classifier.services.classification import ClassificationService
from knowledge_classifier.services.entity_extraction import EntityExtractionService
from knowledge_classifier.services.segmentation import SegmentationService
from knowledge_classifier.services.topic_assignment import TopicAssignmentService
from knowledge_classifier.services.topic_retrieval import TopicRetrievalService

logger = logging.getLogger(__name__)


class KnowledgePipelineService:
    """Orchestrates the full knowledge classification pipeline."""

    def __init__(self, llm_provider: LLMProvider, db_session: Session):
        self.llm = llm_provider
        self.db = db_session
        self.settings = get_settings()
        
        # Initialize sub-services
        self.segmentation_service = SegmentationService(llm_provider, db_session)
        self.classification_service = ClassificationService(llm_provider, db_session)
        self.entity_extraction_service = EntityExtractionService(llm_provider, db_session)
        self.topic_retrieval_service = TopicRetrievalService(db_session)
        self.topic_assignment_service = TopicAssignmentService(llm_provider, db_session)

    def process_scan_unit(self, scan_unit_id: str) -> dict[str, Any]:
        """Process a scan unit through the full pipeline.
        
        Args:
            scan_unit_id: ID of the scan unit to process
            
        Returns:
            Dict with processing results
        """
        logger.info(f"Starting pipeline for scan_unit: {scan_unit_id}")
        
        # Load scan unit and OCR result
        scan_unit = self._get_scan_unit(scan_unit_id)
        if not scan_unit:
            raise ValueError(f"Scan unit not found: {scan_unit_id}")
        
        ocr_result = self._get_ocr_result(scan_unit.source_ocr_result_id)
        if not ocr_result:
            raise ValueError(f"OCR result not found: {scan_unit.source_ocr_result_id}")
        
        try:
            # Step 1: Segmentation
            logger.info("Step 1: Segmenting document")
            scan_unit.status = ScanUnitStatus.PROCESSING.value
            self.db.flush()
            
            segmentation_result = self.segmentation_service.segment_ocr_result(
                ocr_structured=ocr_result.structured_json,
                ocr_markdown=ocr_result.markdown_text,
                page_count=ocr_result.page_count,
            )
            
            # Step 2: Create document units
            logger.info(f"Step 2: Creating {len(segmentation_result.segments)} document units")
            document_units = self._create_document_units(
                scan_unit, segmentation_result
            )
            
            scan_unit.segmentation_confidence = segmentation_result.overall_confidence
            scan_unit.status = ScanUnitStatus.SEGMENTED.value
            self.db.flush()
            
            # Step 3: Classify each document unit
            logger.info("Step 3: Classifying document units")
            classification_results = self._classify_document_units(
                document_units, ocr_result
            )
            
            # Step 4: Extract entities
            logger.info("Step 4: Extracting entities")
            entity_results = self._extract_entities(document_units, ocr_result)
            
            # Step 5: Topic assignment
            logger.info("Step 5: Assigning topics")
            self._assign_topics(document_units, entity_results)
            
            # Update final status
            needs_review = any(
                du.review_status == ReviewStatus.NEEDS_REVIEW.value 
                for du in document_units
            )
            scan_unit.status = ScanUnitStatus.NEEDS_REVIEW.value if needs_review else ScanUnitStatus.ASSIGNED.value
            
            # Calculate overall confidences
            confidences = [du.document_type_confidence or 0 for du in document_units]
            scan_unit.classification_confidence = sum(confidences) / len(confidences) if confidences else 0
            
            self.db.flush()
            
            logger.info(f"Pipeline completed for scan_unit: {scan_unit_id}")
            
            return {
                "scan_unit_id": str(scan_unit.id),
                "status": scan_unit.status,
                "document_units_count": len(document_units),
                "segmentation_confidence": scan_unit.segmentation_confidence,
                "classification_confidence": scan_unit.classification_confidence,
            }
            
        except Exception as e:
            logger.error(f"Pipeline failed for scan_unit {scan_unit_id}: {e}")
            scan_unit.status = ScanUnitStatus.FAILED.value
            self.db.flush()
            raise

    def _get_scan_unit(self, scan_unit_id: str) -> DBScanUnit | None:
        """Get scan unit by ID."""
        from sqlalchemy import select
        result = self.db.execute(
            select(DBScanUnit).where(DBScanUnit.id == uuid.UUID(scan_unit_id))
        )
        return result.scalar_one_or_none()

    def _get_ocr_result(self, ocr_result_id: str) -> OCRResult | None:
        """Get OCR result by ID."""
        from sqlalchemy import select
        result = self.db.execute(
            select(OCRResult).where(OCRResult.id == uuid.UUID(ocr_result_id))
        )
        return result.scalar_one_or_none()

    def _create_document_units(
        self,
        scan_unit: DBScanUnit,
        segmentation_result: Any,
    ) -> list[DBDocumentUnit]:
        """Create document units from segmentation result."""
        document_units = []
        
        for ordinal, segment in enumerate(segmentation_result.segments, 1):
            doc_unit = DBDocumentUnit(
                scan_unit_id=scan_unit.id,
                ordinal=ordinal,
                start_page=segment.start_page,
                end_page=segment.end_page,
                segmentation_confidence=segment.confidence,
                review_status=ReviewStatus.AUTO_ACCEPTED.value if segment.confidence >= self.settings.confidence_threshold_segmentation else ReviewStatus.NEEDS_REVIEW.value,
            )
            self.db.add(doc_unit)
            document_units.append(doc_unit)
        
        # Save LLM decision for segmentation
        if segmentation_result.boundaries:
            self._save_llm_decision(
                scan_unit_id=scan_unit.id,
                decision_type="segmentation",
                input_payload={"page_count": scan_unit.page_count},
                output_payload={"segments": [s.model_dump() for s in segmentation_result.segments]},
            )
        
        return document_units

    def _classify_document_units(
        self,
        document_units: list[DBDocumentUnit],
        ocr_result: OCRResult,
    ) -> list[Any]:
        """Classify all document units."""
        results = []
        
        for doc_unit in document_units:
            # Extract text for this segment
            segment_text = self._extract_segment_text(
                ocr_result.markdown_text,
                doc_unit.start_page,
                doc_unit.end_page,
                ocr_result.page_count
            )
            
            classification = self.classification_service.classify_document(segment_text)
            
            # Update document unit
            doc_unit.document_type_code = classification.primary_type.type_code
            doc_unit.document_type_confidence = classification.primary_type.confidence
            doc_unit.extracted_summary = classification.rationale[:500] if classification.rationale else None
            
            # Set review status based on confidence
            if classification.primary_type.confidence < self.settings.confidence_threshold_classification:
                doc_unit.review_status = ReviewStatus.NEEDS_REVIEW.value
            
            # Save LLM decision
            self._save_llm_decision(
                document_unit_id=doc_unit.id,
                decision_type="classification",
                input_payload={"text_length": len(segment_text)},
                output_payload=classification.model_dump(),
            )
            
            results.append(classification)
        
        return results

    def _extract_entities(
        self,
        document_units: list[DBDocumentUnit],
        ocr_result: OCRResult,
    ) -> dict[uuid.UUID, Any]:
        """Extract entities for all document units."""
        results = {}
        
        for doc_unit in document_units:
            segment_text = self._extract_segment_text(
                ocr_result.markdown_text,
                doc_unit.start_page,
                doc_unit.end_page,
                ocr_result.page_count
            )
            
            entity_result = self.entity_extraction_service.extract_entities(
                segment_text,
                doc_unit.start_page,
                doc_unit.end_page,
            )
            
            # Save entities to database
            for entity in entity_result.entities:
                db_entity = DBDocumentUnitEntity(
                    document_unit_id=doc_unit.id,
                    entity_type=entity.entity_type,
                    entity_value=entity.entity_value,
                    normalized_value=entity.normalized_value,
                    confidence=entity.confidence,
                    page_from=entity.page_from,
                    page_to=entity.page_to,
                )
                self.db.add(db_entity)
            
            # Update summary if better one available
            if entity_result.summary and not doc_unit.extracted_summary:
                doc_unit.extracted_summary = entity_result.summary
            
            results[doc_unit.id] = entity_result
        
        return results

    def _assign_topics(
        self,
        document_units: list[DBDocumentUnit],
        entity_results: dict[uuid.UUID, Any],
    ):
        """Assign topics to all document units."""
        for doc_unit in document_units:
            entity_result = entity_results.get(doc_unit.id)
            entities = entity_result.entities if entity_result else []
            
            # Retrieve candidate topics
            candidates_result = self.topic_retrieval_service.retrieve_candidates(
                document_type_code=doc_unit.document_type_code,
                document_title=doc_unit.title,
                document_summary=doc_unit.extracted_summary,
                entities=entities,
            )
            
            # Make assignment decision
            decision = self.topic_assignment_service.assign_topic(
                document_type_code=doc_unit.document_type_code,
                document_title=doc_unit.title,
                document_summary=doc_unit.extracted_summary,
                entities=entities,
                candidates=candidates_result.candidates,
            )
            
            # Execute decision
            if decision.action == "assign_existing":
                self._create_topic_assignments(doc_unit, decision)
            elif decision.action == "assign_multiple":
                self._create_topic_assignments(doc_unit, decision)
            elif decision.action == "propose_new":
                self._create_topic_proposal(doc_unit, decision)
            elif decision.action == "needs_review":
                doc_unit.review_status = ReviewStatus.NEEDS_REVIEW.value
                # Still create tentative assignment
                self._create_topic_assignments(doc_unit, decision)
            
            # Save LLM decision
            self._save_llm_decision(
                document_unit_id=doc_unit.id,
                decision_type="topic_assignment",
                input_payload={"candidates_count": len(candidates_result.candidates)},
                output_payload=decision.model_dump(),
            )

    def _create_topic_assignments(
        self,
        doc_unit: DBDocumentUnit,
        decision: Any,
    ):
        """Create topic assignments from decision."""
        for topic_id, role in zip(decision.topic_ids, decision.assignment_roles):
            assignment = DBDocumentUnitTopicAssignment(
                document_unit_id=doc_unit.id,
                topic_id=uuid.UUID(topic_id),
                assignment_role=role,
                confidence=decision.confidence,
                rationale=decision.rationale,
            )
            self.db.add(assignment)

    def _create_topic_proposal(
        self,
        doc_unit: DBDocumentUnit,
        decision: Any,
    ):
        """Create topic proposal from decision."""
        if not decision.proposed_topic:
            return
        
        proposal = TopicProposal(
            proposed_slug=decision.proposed_topic.get("proposed_slug", "unknown"),
            proposed_title=decision.proposed_topic.get("proposed_title", "Unknown"),
            topic_class=decision.proposed_topic.get("topic_class", "other"),
            description=decision.proposed_topic.get("description"),
            proposal_status=TopicProposalStatus.PROPOSED.value,
            source_document_unit_id=doc_unit.id,
            confidence=decision.confidence,
            rationale=decision.rationale,
        )
        self.db.add(proposal)
        doc_unit.review_status = ReviewStatus.NEEDS_REVIEW.value

    def _extract_segment_text(
        self,
        markdown: str,
        start_page: int,
        end_page: int,
        total_pages: int,
    ) -> str:
        """Extract text for a page segment from markdown."""
        lines = markdown.split("\n")
        lines_per_page = max(1, len(lines) // total_pages)
        
        start_idx = (start_page - 1) * lines_per_page
        end_idx = end_page * lines_per_page
        
        return "\n".join(lines[start_idx:end_idx])

    def _save_llm_decision(
        self,
        scan_unit_id: uuid.UUID | None = None,
        document_unit_id: uuid.UUID | None = None,
        decision_type: str = "",
        input_payload: dict = None,
        output_payload: dict = None,
    ):
        """Save LLM decision to database."""
        decision = LLMDecision(
            scan_unit_id=scan_unit_id,
            document_unit_id=document_unit_id,
            decision_type=decision_type,
            model_name=self.settings.llm_model,
            prompt_version="v1",
            input_payload_json=input_payload or {},
            output_payload_json=output_payload or {},
        )
        self.db.add(decision)
