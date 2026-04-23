"""Knowledge pipeline service - orchestrates the full classification pipeline."""

import logging
import re
import uuid
from typing import Any

from sqlalchemy import insert, select
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
from knowledge_classifier.services.pipeline_strategies import (
    FinancialPipelineStrategy,
    GeneralPipelineStrategy,
    MeetingPipelineStrategy,
    NormativePipelineStrategy,
    TechnicalAdminPipelineStrategy,
    UtilityVendorPipelineStrategy,
)
from knowledge_classifier.services.routing import PipelineRouterService
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
        self.pipeline_router_service = PipelineRouterService()
        self.pipeline_strategies = {
            "general_pipeline": GeneralPipelineStrategy(),
            "normative_pipeline": NormativePipelineStrategy(),
            "meeting_pipeline": MeetingPipelineStrategy(),
            "financial_pipeline": FinancialPipelineStrategy(),
            "utility_vendor_pipeline": UtilityVendorPipelineStrategy(),
            "technical_admin_pipeline": TechnicalAdminPipelineStrategy(),
        }

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
            routing_decision = self.pipeline_router_service.route_scan(ocr_result)
            strategy = self._resolve_pipeline_strategy(routing_decision.pipeline_id)
            logger.info(
                "Routing scan_unit %s to %s (%s)",
                scan_unit_id,
                routing_decision.pipeline_id,
                routing_decision.family,
            )
            self._save_llm_decision(
                scan_unit_id=scan_unit.id,
                decision_type="pipeline_routing",
                input_payload={"page_count": ocr_result.page_count},
                output_payload=routing_decision.model_dump(),
            )

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
            self._assign_topics(scan_unit, document_units, entity_results)
            strategy.postprocess(self, scan_unit, document_units, entity_results, ocr_result)
            
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
                "pipeline_id": routing_decision.pipeline_id,
                "pipeline_family": routing_decision.family,
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
        # Handle both string and UUID input
        if isinstance(scan_unit_id, str):
            scan_unit_id = uuid.UUID(scan_unit_id)
        result = self.db.execute(
            select(DBScanUnit).where(DBScanUnit.id == scan_unit_id)
        )
        return result.scalar_one_or_none()

    def _resolve_pipeline_strategy(self, pipeline_id: str):
        """Resolve the selected pipeline strategy, defaulting to the general pipeline."""
        return self.pipeline_strategies.get(
            pipeline_id,
            self.pipeline_strategies["general_pipeline"],
        )

    def _get_ocr_result(self, ocr_result_id) -> OCRResult | None:
        """Get OCR result by ID."""
        # Handle both string and UUID input
        if isinstance(ocr_result_id, str):
            ocr_result_id = uuid.UUID(ocr_result_id)
        result = self.db.execute(
            select(OCRResult).where(OCRResult.id == ocr_result_id)
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
            self._set_document_type(doc_unit, classification.primary_type.type_code)
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

            entities = self._normalize_entities(
                entity_result.entities,
                doc_unit.start_page,
                doc_unit.end_page,
            )
            entity_result.entities = entities
            
            # Save entities to database
            for entity in entities:
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
        scan_unit: DBScanUnit,
        document_units: list[DBDocumentUnit],
        entity_results: dict[uuid.UUID, Any],
    ):
        """Assign topics to all document units."""
        for doc_unit in document_units:
            entity_result = entity_results.get(doc_unit.id)
            entities = entity_result.entities if entity_result else []
            document_type_code = self._get_document_type_code(doc_unit)
            
            # Retrieve candidate topics
            candidates_result = self.topic_retrieval_service.retrieve_candidates(
                document_type_code=document_type_code,
                document_title=doc_unit.title,
                document_summary=doc_unit.extracted_summary,
                entities=entities,
            )
            
            # Make assignment decision
            decision = self.topic_assignment_service.assign_topic(
                document_type_code=document_type_code,
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
                reused_proposal = self._find_reusable_topic_proposal(scan_unit, decision, entities)
                if reused_proposal and reused_proposal.matched_existing_topic_id:
                    doc_unit.review_status = ReviewStatus.NEEDS_REVIEW.value
                    decision.action = "assign_existing"
                    decision.topic_ids = [str(reused_proposal.matched_existing_topic_id)]
                    decision.assignment_roles = ["primary"]
                    decision.rationale = (
                        f"{decision.rationale} Reused provisional topic from the same scan "
                        f"to avoid duplicate topic proposals."
                    )
                    self._create_topic_assignments(doc_unit, decision)
                else:
                    self._create_topic_proposal(scan_unit, doc_unit, decision, entities)
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
        scan_unit: DBScanUnit,
        doc_unit: DBDocumentUnit,
        decision: Any,
        entities: list[Any],
    ):
        """Create topic proposal from decision."""
        if not decision.proposed_topic:
            return

        proposed_slug = decision.proposed_topic.get("proposed_slug", "unknown")
        proposed_title = decision.proposed_topic.get("proposed_title", "Unknown")
        provisional_topic = self._find_topic_by_slug(proposed_slug)
        if provisional_topic is None:
            provisional_topic = DBTopic(
                slug=proposed_slug,
                title=proposed_title,
                topic_class=decision.proposed_topic.get("topic_class", "other"),
                description=decision.proposed_topic.get("description"),
                canonical=False,
                is_active=False,
            )
            self.db.add(provisional_topic)
            self.db.flush()

        proposal = TopicProposal(
            proposed_slug=proposed_slug,
            proposed_title=proposed_title,
            topic_class=decision.proposed_topic.get("topic_class", "other"),
            description=decision.proposed_topic.get("description"),
            proposal_status=TopicProposalStatus.PROPOSED.value,
            source_document_unit_id=doc_unit.id,
            matched_existing_topic_id=provisional_topic.id,
            confidence=decision.confidence,
            rationale=decision.rationale,
        )
        self.db.add(proposal)
        assignment = DBDocumentUnitTopicAssignment(
            document_unit_id=doc_unit.id,
            topic_id=provisional_topic.id,
            assignment_role="primary",
            confidence=decision.confidence,
            rationale=decision.rationale,
        )
        self.db.add(assignment)
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

    def _set_document_type(self, doc_unit: DBDocumentUnit, type_code: str) -> None:
        """Resolve and persist the document type by code."""
        result = self.db.execute(
            select(DBDocumentType).where(DBDocumentType.code == type_code)
        )
        document_type = result.scalar_one_or_none()
        if document_type is None:
            logger.warning("Unknown document type code returned by classifier: %s", type_code)
            return
        doc_unit.document_type_id = document_type.id
        doc_unit.document_type = document_type

    def _get_document_type_code(self, doc_unit: DBDocumentUnit) -> str | None:
        """Return the persisted document type code for a document unit."""
        if doc_unit.document_type is not None:
            return doc_unit.document_type.code
        if doc_unit.document_type_id is None:
            return None
        result = self.db.execute(
            select(DBDocumentType).where(DBDocumentType.id == doc_unit.document_type_id)
        )
        document_type = result.scalar_one_or_none()
        if document_type is None:
            return None
        doc_unit.document_type = document_type
        return document_type.code

    def _normalize_entities(
        self,
        entities: list[Any],
        start_page: int,
        end_page: int,
    ) -> list[Any]:
        """Deduplicate entities and convert page numbers to scan-level coordinates."""
        normalized_entities: list[Any] = []
        seen: set[tuple[str, str, int | None, int | None]] = set()
        segment_length = max(1, end_page - start_page + 1)

        for entity in entities:
            page_from = entity.page_from
            page_to = entity.page_to

            if page_from is None:
                page_from = start_page
            elif 1 <= page_from <= segment_length and page_from < start_page:
                page_from = start_page + page_from - 1

            if page_to is None:
                page_to = end_page if page_from != start_page else page_from
            elif 1 <= page_to <= segment_length and page_to < start_page:
                page_to = start_page + page_to - 1

            page_from = max(start_page, min(page_from, end_page))
            page_to = max(page_from, min(page_to, end_page))

            entity.page_from = page_from
            entity.page_to = page_to
            if not entity.normalized_value:
                entity.normalized_value = self._normalize_entity_value(entity.entity_value)

            dedupe_key = (
                entity.entity_type.strip().lower(),
                entity.entity_value.strip().lower(),
                entity.page_from,
                entity.page_to,
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalized_entities.append(entity)

        return normalized_entities

    def _normalize_entity_value(self, value: str) -> str:
        """Create a stable normalized value for extracted entities."""
        normalized = value.strip().lower()
        normalized = re.sub(r"\s+", "_", normalized)
        normalized = re.sub(r"[^a-z0-9_./-]+", "", normalized)
        return normalized

    def _find_reusable_topic_proposal(
        self,
        scan_unit: DBScanUnit,
        decision: Any,
        entities: list[Any],
    ) -> TopicProposal | None:
        """Reuse a proposal already created in the same scan when it clearly targets the same topic."""
        result = self.db.execute(
            select(TopicProposal)
            .join(DBDocumentUnit, TopicProposal.source_document_unit_id == DBDocumentUnit.id)
            .where(DBDocumentUnit.scan_unit_id == scan_unit.id)
            .where(TopicProposal.proposal_status == TopicProposalStatus.PROPOSED.value)
            .order_by(TopicProposal.created_at.asc())
        )
        proposals = list(result.scalars().all())
        if not proposals:
            return None

        new_slug = self._proposal_key(decision.proposed_topic.get("proposed_slug", ""))
        new_title = self._proposal_key(decision.proposed_topic.get("proposed_title", ""))
        new_anchor = self._topic_anchor(entities, new_slug, new_title)

        for proposal in proposals:
            proposal_key = self._proposal_key(proposal.proposed_slug)
            proposal_title = self._proposal_key(proposal.proposed_title)
            proposal_anchor = self._topic_anchor([], proposal_key, proposal_title)
            if (
                new_anchor
                and proposal_anchor
                and self._proposal_similarity(new_anchor, proposal_anchor) >= 0.6
            ):
                return proposal
            if (
                new_slug
                and proposal_key
                and self._proposal_similarity(new_slug, proposal_key) >= 0.75
            ):
                return proposal
            if (
                new_title
                and proposal_title
                and self._proposal_similarity(new_title, proposal_title) >= 0.75
            ):
                return proposal
        return None

    def _topic_anchor(self, entities: list[Any], *fallback_texts: str) -> str | None:
        """Build a coarse topic anchor, preferring condominium/address entities."""
        for preferred_type in ("condominio", "indirizzo"):
            for entity in entities:
                if entity.entity_type == preferred_type:
                    return self._proposal_key(entity.normalized_value or entity.entity_value)

        for text in fallback_texts:
            key = self._proposal_key(text)
            if key:
                tokens = [
                    token
                    for token in key.split("_")
                    if token
                    not in {
                        "bilancio",
                        "preventivo",
                        "riparto",
                        "spese",
                        "case",
                        "file",
                        "financial",
                        "period",
                        "condominio",
                        "scandicci",
                        "via",
                        "di",
                    }
                ]
                if tokens:
                    return "_".join(tokens[:6])
        return None

    def _proposal_key(self, value: str) -> str:
        """Normalize proposal text for approximate equality checks."""
        key = value.strip().lower()
        key = re.sub(r"[^a-z0-9]+", "_", key)
        key = re.sub(r"_+", "_", key).strip("_")
        return key

    def _proposal_similarity(self, left: str, right: str) -> float:
        """Compute a simple token-overlap similarity for proposal consolidation."""
        left_tokens = set(left.split("_")) - {"", "condominio", "via", "di", "scandicci"}
        right_tokens = set(right.split("_")) - {"", "condominio", "via", "di", "scandicci"}
        if not left_tokens or not right_tokens:
            return 0.0
        intersection = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return intersection / union if union else 0.0

    def _find_topic_by_slug(self, slug: str) -> DBTopic | None:
        """Find an existing topic by slug."""
        result = self.db.execute(select(DBTopic).where(DBTopic.slug == slug))
        return result.scalar_one_or_none()

    def _consolidate_scan_topics(
        self,
        scan_unit: DBScanUnit,
        document_units: list[DBDocumentUnit],
        entity_results: dict[uuid.UUID, Any],
    ) -> None:
        """Merge duplicate proposed topics generated for the same scan."""
        canonical_groups: list[tuple[str, TopicProposal]] = []

        for doc_unit in document_units:
            entity_result = entity_results.get(doc_unit.id)
            entities = entity_result.entities if entity_result else []
            anchor = self._topic_anchor(entities)
            if not anchor:
                continue

            proposal = self.db.execute(
                select(TopicProposal).where(TopicProposal.source_document_unit_id == doc_unit.id)
            ).scalar_one_or_none()
            if proposal is None or proposal.matched_existing_topic_id is None:
                continue

            canonical = None
            for existing_anchor, existing_proposal in canonical_groups:
                if self._proposal_similarity(anchor, existing_anchor) >= 0.6:
                    canonical = existing_proposal
                    break
            if canonical is None:
                canonical_groups.append((anchor, proposal))
                continue

            if canonical.id == proposal.id:
                continue

            self._reassign_document_unit_topic(doc_unit.id, proposal.matched_existing_topic_id, canonical.matched_existing_topic_id)
            self.db.delete(proposal)

            duplicate_topic = self.db.execute(
                select(DBTopic).where(DBTopic.id == proposal.matched_existing_topic_id)
            ).scalar_one_or_none()
            if duplicate_topic is not None:
                remaining_assignments = self.db.execute(
                    select(DBDocumentUnitTopicAssignment).where(
                        DBDocumentUnitTopicAssignment.topic_id == duplicate_topic.id
                    )
                ).scalars().all()
                remaining_proposals = self.db.execute(
                    select(TopicProposal).where(TopicProposal.matched_existing_topic_id == duplicate_topic.id)
                ).scalars().all()
                if not remaining_assignments and not remaining_proposals:
                    self.db.delete(duplicate_topic)

    def _consolidate_financial_topics(
        self,
        scan_unit: DBScanUnit,
        document_units: list[DBDocumentUnit],
        entity_results: dict[uuid.UUID, Any],
    ) -> None:
        """Merge duplicate financial/vendor proposals using vendor-first anchors."""
        canonical_groups: list[tuple[str, TopicProposal]] = []

        for doc_unit in document_units:
            document_type_code = self._get_document_type_code(doc_unit)
            if document_type_code not in {
                "fattura",
                "preventivo",
                "riparto_spese",
                "rendiconto_contabile",
            }:
                continue

            entity_result = entity_results.get(doc_unit.id)
            entities = entity_result.entities if entity_result else []
            anchor = self._financial_topic_anchor(entities)
            if not anchor:
                continue

            proposal = self.db.execute(
                select(TopicProposal).where(TopicProposal.source_document_unit_id == doc_unit.id)
            ).scalar_one_or_none()
            if proposal is None or proposal.matched_existing_topic_id is None:
                continue

            canonical = None
            for existing_anchor, existing_proposal in canonical_groups:
                if self._proposal_similarity(anchor, existing_anchor) >= 0.75:
                    canonical = existing_proposal
                    break
            if canonical is None:
                canonical_groups.append((anchor, proposal))
                continue

            if canonical.id == proposal.id:
                continue

            self._reassign_document_unit_topic(
                doc_unit.id,
                proposal.matched_existing_topic_id,
                canonical.matched_existing_topic_id,
            )
            self.db.delete(proposal)

            duplicate_topic = self.db.execute(
                select(DBTopic).where(DBTopic.id == proposal.matched_existing_topic_id)
            ).scalar_one_or_none()
            if duplicate_topic is not None:
                remaining_assignments = self.db.execute(
                    select(DBDocumentUnitTopicAssignment).where(
                        DBDocumentUnitTopicAssignment.topic_id == duplicate_topic.id
                    )
                ).scalars().all()
                remaining_proposals = self.db.execute(
                    select(TopicProposal).where(TopicProposal.matched_existing_topic_id == duplicate_topic.id)
                ).scalars().all()
                if not remaining_assignments and not remaining_proposals:
                    self.db.delete(duplicate_topic)

    def _update_scan_assignment_confidence(
        self,
        scan_unit: DBScanUnit,
        document_units: list[DBDocumentUnit],
    ) -> None:
        """Recompute the scan-level assignment confidence from unit assignments."""
        confidences = [
            assignment.confidence
            for doc_unit in document_units
            for assignment in doc_unit.topic_assignments
            if assignment.confidence is not None
        ]
        if confidences:
            scan_unit.assignment_confidence = sum(confidences) / len(confidences)

    def _financial_topic_anchor(self, entities: list[Any]) -> str | None:
        """Build a vendor-first anchor for financial documents."""
        for preferred_type in ("fornitore", "organizzazione", "persona", "indirizzo"):
            for entity in entities:
                if entity.entity_type == preferred_type:
                    return self._proposal_key(entity.normalized_value or entity.entity_value)
        return None

    def _consolidate_scan_semantics(
        self,
        scan_unit: DBScanUnit,
        document_units: list[DBDocumentUnit],
        entity_results: dict[uuid.UUID, Any],
        ocr_result: OCRResult,
    ) -> None:
        """Apply scan-level semantic normalization after first-pass classification/topicing."""
        if not document_units:
            return

        scan_text = " ".join(
            filter(
                None,
                [
                    ocr_result.full_text[:20000] if ocr_result.full_text else "",
                    " ".join(
                        doc_unit.extracted_summary or ""
                        for doc_unit in document_units
                    ),
                ],
            )
        ).lower()

        if self._looks_like_condominium_regulation(scan_text, document_units):
            self._normalize_regulation_scan(document_units, entity_results)

    def _looks_like_condominium_regulation(
        self,
        scan_text: str,
        document_units: list[DBDocumentUnit],
    ) -> bool:
        """Detect long-form normative condominium regulations split into multiple units."""
        if "regolamento" not in scan_text or "condominio" not in scan_text:
            return False

        article_markers = scan_text.count("art.") + scan_text.count("articolo")
        if article_markers < 3:
            return False

        type_codes = [self._get_document_type_code(doc_unit) for doc_unit in document_units]
        allowed_types = {"contratto", "verbale_assemblea", "lettera", "altro"}
        classified = [type_code for type_code in type_codes if type_code]
        if not classified or any(type_code not in allowed_types for type_code in classified):
            return False

        return len(document_units) >= 2

    def _normalize_regulation_scan(
        self,
        document_units: list[DBDocumentUnit],
        entity_results: dict[uuid.UUID, Any],
    ) -> None:
        """Force coherence for scans that are clearly one condominium regulation."""
        canonical_doc_unit = self._pick_regulation_canonical_unit(document_units, entity_results)
        if canonical_doc_unit is None:
            return

        canonical_proposal = self.db.execute(
            select(TopicProposal).where(TopicProposal.source_document_unit_id == canonical_doc_unit.id)
        ).scalar_one_or_none()
        canonical_topic_id = canonical_proposal.matched_existing_topic_id if canonical_proposal else None

        for doc_unit in document_units:
            doc_unit.review_status = ReviewStatus.NEEDS_REVIEW.value
            self._set_document_type(doc_unit, "contratto")
            if (doc_unit.document_type_confidence or 0.0) < 0.95:
                doc_unit.document_type_confidence = 0.95
            if not doc_unit.title:
                doc_unit.title = canonical_doc_unit.title or "Regolamento condominiale"

            proposal = self.db.execute(
                select(TopicProposal).where(TopicProposal.source_document_unit_id == doc_unit.id)
            ).scalar_one_or_none()
            if canonical_proposal is not None and proposal is not None and proposal.id != canonical_proposal.id:
                if proposal.matched_existing_topic_id and canonical_topic_id:
                    self._reassign_document_unit_topic(
                        doc_unit.id,
                        proposal.matched_existing_topic_id,
                        canonical_topic_id,
                    )
                self.db.delete(proposal)

            if canonical_topic_id is not None and doc_unit.id != canonical_doc_unit.id:
                assignments = self.db.execute(
                    select(DBDocumentUnitTopicAssignment).where(
                        DBDocumentUnitTopicAssignment.document_unit_id == doc_unit.id
                    )
                ).scalars().all()
                if assignments:
                    for assignment in assignments:
                        assignment.topic_id = canonical_topic_id
                        assignment.assignment_role = "primary"
                        assignment.confidence = max(assignment.confidence or 0.0, 0.92)
                        assignment.rationale = (
                            "Consolidated at scan level: this scan is a single condominium regulation "
                            "split across multiple OCR/classification segments."
                        )
                else:
                    assignment = DBDocumentUnitTopicAssignment(
                        document_unit_id=doc_unit.id,
                        topic_id=canonical_topic_id,
                        assignment_role="primary",
                        confidence=0.92,
                        rationale=(
                            "Consolidated at scan level: this scan is a single condominium regulation "
                            "split across multiple OCR/classification segments."
                        ),
                    )
                    self.db.add(assignment)

    def _pick_regulation_canonical_unit(
        self,
        document_units: list[DBDocumentUnit],
        entity_results: dict[uuid.UUID, Any],
    ) -> DBDocumentUnit | None:
        """Choose the document unit with the strongest condominium anchor/proposal."""
        best_doc_unit: DBDocumentUnit | None = None
        best_score = -1

        for doc_unit in document_units:
            score = 0
            entity_result = entity_results.get(doc_unit.id)
            entities = entity_result.entities if entity_result else []
            if any(entity.entity_type == "condominio" for entity in entities):
                score += 4
            if any(entity.entity_type == "indirizzo" for entity in entities):
                score += 2
            if doc_unit.proposal is not None:
                score += 3
            summary = (doc_unit.extracted_summary or "").lower()
            if "regolamento" in summary:
                score += 2
            if "condominio" in summary:
                score += 1
            if score > best_score:
                best_score = score
                best_doc_unit = doc_unit

        return best_doc_unit

    def _reassign_document_unit_topic(
        self,
        document_unit_id: uuid.UUID,
        old_topic_id: uuid.UUID | None,
        new_topic_id: uuid.UUID | None,
    ) -> None:
        """Point existing assignments for a document unit to the canonical provisional topic."""
        if old_topic_id is None or new_topic_id is None or old_topic_id == new_topic_id:
            return

        assignments = self.db.execute(
            select(DBDocumentUnitTopicAssignment).where(
                DBDocumentUnitTopicAssignment.document_unit_id == document_unit_id
            )
        ).scalars().all()

        for assignment in assignments:
            if assignment.topic_id == old_topic_id:
                assignment.topic_id = new_topic_id
