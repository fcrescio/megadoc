"""Topic retrieval service."""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import Topic, TopicAlias
from knowledge_classifier.config import get_settings
from knowledge_classifier.schemas import ExtractedEntity, TopicCandidate, TopicRetrievalResult

logger = logging.getLogger(__name__)


class TopicRetrievalService:
    """Service for retrieving candidate topics for document assignment."""

    def __init__(self, db_session: Session):
        self.db = db_session
        self.settings = get_settings()

    def retrieve_candidates(
        self,
        document_type_code: str | None,
        document_title: str | None,
        document_summary: str | None,
        entities: list[ExtractedEntity],
        limit: int | None = None,
    ) -> TopicRetrievalResult:
        """Retrieve candidate topics for a document.
        
        Uses simple scoring based on:
        - Entity matches with topic aliases/titles
        - Document type compatibility
        - Keyword overlap
        
        Args:
            document_type_code: Classified document type
            document_title: Document title
            document_summary: Document summary
            entities: Extracted entities
            limit: Max candidates to return
            
        Returns:
            TopicRetrievalResult with scored candidates
        """
        if limit is None:
            limit = self.settings.max_topics_to_retrieve
        
        # Get all active topics with their aliases
        topics_result = self.db.execute(
            select(Topic).where(Topic.is_active == True)
        )
        topics = list(topics_result.scalars().all())
        
        if not topics:
            return TopicRetrievalResult(candidates=[], has_strong_match=False)
        
        # Build search terms from document
        search_terms = self._build_search_terms(
            document_title, document_summary, entities
        )
        
        # Score each topic
        scored_topics: list[tuple[Topic, float, list[str]]] = []
        
        for topic in topics:
            score, reasons = self._score_topic(
                topic, document_type_code, search_terms
            )
            if score > 0:
                scored_topics.append((topic, score, reasons))
        
        # Sort by score descending
        scored_topics.sort(key=lambda x: x[1], reverse=True)
        
        # Build candidates
        candidates = []
        for topic, score, reasons in scored_topics[:limit]:
            candidates.append(TopicCandidate(
                topic_id=str(topic.id),
                slug=topic.slug,
                title=topic.title,
                score=min(score, 1.0),
                reasons=reasons
            ))
        
        # Check for strong match
        has_strong_match = len(candidates) > 0 and candidates[0].score >= 0.7
        
        return TopicRetrievalResult(
            candidates=candidates,
            has_strong_match=has_strong_match
        )

    def _build_search_terms(
        self,
        title: str | None,
        summary: str | None,
        entities: list[ExtractedEntity],
    ) -> dict[str, Any]:
        """Build search terms from document metadata."""
        terms: dict[str, Any] = {
            "title_words": set(),
            "summary_words": set(),
            "entity_values": set(),
            "entity_normalized": set(),
        }
        
        if title:
            terms["title_words"] = self._tokenize(title.lower())
        
        if summary:
            terms["summary_words"] = self._tokenize(summary.lower())
        
        for entity in entities:
            terms["entity_values"].add(entity.entity_value.lower())
            if entity.normalized_value:
                terms["entity_normalized"].add(entity.normalized_value.lower())
        
        return terms

    def _score_topic(
        self,
        topic: Topic,
        document_type_code: str | None,
        search_terms: dict[str, Any],
    ) -> tuple[float, list[str]]:
        """Score a topic based on document data."""
        score = 0.0
        reasons = []
        
        topic_title_lower = topic.title.lower()
        topic_slug_lower = topic.slug.lower()
        topic_desc_lower = (topic.description or "").lower()
        
        topic_words = self._tokenize(topic_title_lower)
        
        # Title match (high weight)
        title_matches = search_terms["title_words"] & topic_words
        if title_matches:
            score += len(title_matches) * 0.3
            reasons.append(f"Title match: {', '.join(title_matches)}")
        
        # Slug match (high weight)
        slug_matches = search_terms["title_words"] & self._tokenize(topic_slug_lower)
        if slug_matches:
            score += len(slug_matches) * 0.25
            reasons.append(f"Slug match: {', '.join(slug_matches)}")
        
        # Entity value match (medium weight)
        for entity_val in search_terms["entity_values"]:
            if entity_val in topic_title_lower or entity_val in topic_slug_lower:
                score += 0.2
                reasons.append(f"Entity match: {entity_val}")
                break
        
        # Normalized entity match (medium weight)
        for norm_val in search_terms["entity_normalized"]:
            if norm_val in topic_slug_lower:
                score += 0.25
                reasons.append(f"Normalized entity match: {norm_val}")
                break
        
        # Summary overlap (low weight)
        summary_overlap = search_terms["summary_words"] & topic_words
        if summary_overlap:
            score += len(summary_overlap) * 0.1
            if len(summary_overlap) >= 3:
                reasons.append(f"Summary overlap: {len(summary_overlap)} terms")
        
        # Description match (low weight)
        if topic_desc_lower:
            desc_words = self._tokenize(topic_desc_lower)
            desc_overlap = search_terms["summary_words"] & desc_words
            if desc_overlap:
                score += len(desc_overlap) * 0.05
        
        # Document type compatibility (bonus)
        if document_type_code and topic.topic_class:
            type_compatibility = self._check_type_compatibility(
                document_type_code, topic.topic_class
            )
            if type_compatibility > 0:
                score += type_compatibility * 0.1
                reasons.append(f"Type compatible: {topic.topic_class}")
        
        return score, reasons[:5]  # Limit reasons

    def _tokenize(self, text: str) -> set[str]:
        """Simple tokenization."""
        import re
        # Remove stopwords and tokenize
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "di", "la", "il", "lo", "le", "i", "un", "una", "del", "della",
            "e", "o", "ma", "se", "per", "con", "su", "in", "a", "da"
        }
        words = re.findall(r"\b[a-zàéìòù]{3,}\b", text.lower())
        return {w for w in words if w not in stopwords}

    def _check_type_compatibility(
        self,
        document_type: str,
        topic_class: str,
    ) -> float:
        """Check if document type is compatible with topic class."""
        compatibility_map = {
            "verbale_assemblea": {"meeting": 1.0, "general_administration": 0.5},
            "rendiconto_contabile": {"financial_period": 1.0, "case_file": 0.5},
            "riparto_spese": {"financial_period": 1.0},
            "fattura": {"vendor_relationship": 0.7, "financial_period": 0.5},
            "preventivo": {"vendor_relationship": 0.7, "building_issue": 0.5},
            "bolletta": {"vendor_relationship": 0.8, "building_issue": 0.5},
            "contratto": {"legal_matter": 1.0, "vendor_relationship": 0.6},
            "lettera": {"general_administration": 0.6, "legal_matter": 0.4},
        }
        
        compatible = compatibility_map.get(document_type, {})
        return compatible.get(topic_class, 0.0)
