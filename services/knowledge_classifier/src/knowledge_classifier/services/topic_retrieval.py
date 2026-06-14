"""Topic retrieval service."""

import logging
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common.db.models import DocumentUnitTopicAssignment, Topic, TopicAlias
from knowledge_classifier.config import get_settings
from knowledge_classifier.schemas import ExtractedEntity, TopicCandidate, TopicRetrievalResult

logger = logging.getLogger(__name__)


class TopicRetrievalService:
    """Service for retrieving candidate topics for document assignment."""

    def __init__(self, db_session: Session):
        self.db = db_session
        self.settings = get_settings()

    def _load_assignment_counts(self) -> dict[str, int]:
        """Load assignment counts for all active topics."""
        rows = self.db.execute(
            select(
                DocumentUnitTopicAssignment.topic_id,
                func.count(DocumentUnitTopicAssignment.id).label("cnt"),
            )
            .group_by(DocumentUnitTopicAssignment.topic_id)
        ).all()
        return {str(row.topic_id): row.cnt for row in rows}

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
        
        # Load assignment counts
        assignment_counts = self._load_assignment_counts()
        
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
            # Apply penalty for single-assignment topics with specific/date-like titles
            count = assignment_counts.get(str(topic.id), 0)
            if count <= 1 and self._looks_like_specific_topic(topic):
                score *= 0.5
                reasons.append("Penalty: single-assignment specific topic")
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
                topic_kind=topic.topic_kind,
                assignment_count=assignment_counts.get(str(topic.id), 0),
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
            "anchors": [],
        }
        
        if title:
            terms["title_words"] = self._tokenize(title.lower())
        
        if summary:
            terms["summary_words"] = self._tokenize(summary.lower())
        
        for entity in entities:
            terms["entity_values"].add(entity.entity_value.lower())
            if entity.normalized_value:
                terms["entity_normalized"].add(entity.normalized_value.lower())
            if entity.entity_type in {"indirizzo", "condominio"}:
                anchor = self._anchor_tokens(entity.normalized_value or entity.entity_value)
                if anchor:
                    terms["anchors"].append(anchor)
        
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
        topic_anchor = self._topic_anchor_tokens(
            f"{topic_title_lower} {topic_slug_lower} {topic_desc_lower}"
        )

        for document_anchor in search_terms["anchors"]:
            if topic_anchor and document_anchor and document_anchor.isdisjoint(topic_anchor):
                return 0.0, [
                    "Anchor mismatch: document building/address differs from topic"
                ]
        
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
        # Remove stopwords and tokenize
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "di", "la", "il", "lo", "le", "i", "un", "una", "del", "della",
            "e", "o", "ma", "se", "per", "con", "su", "in", "a", "da"
        }
        words = re.findall(r"\b[a-zàéìòù]{3,}\b", text.lower())
        return {w for w in words if w not in stopwords}

    def _anchor_tokens(self, text: str | None) -> set[str]:
        """Extract building/address identity tokens, excluding generic topic words."""
        if not text:
            return set()

        normalized = text.replace("_", " ")
        generic = {
            "amministrazione",
            "assemblea",
            "bilancio",
            "case",
            "condominio",
            "consuntivo",
            "contabile",
            "documento",
            "documents",
            "edificio",
            "fascicolo",
            "file",
            "finanziario",
            "fiscal",
            "financial",
            "for",
            "gestione",
            "ordinaria",
            "period",
            "periodo",
            "preventivo",
            "rendiconto",
            "riparto",
            "scandicci",
            "spese",
            "straordinaria",
            "verbale",
            "year",
        }
        street_words = {
            "via",
            "viale",
            "piazza",
            "corso",
            "largo",
            "vicolo",
            "strada",
            "localita",
            "località",
        }
        return self._tokenize(normalized) - generic - street_words

    def _topic_anchor_tokens(self, text: str | None) -> set[str]:
        """Extract topic anchors only when the topic explicitly names a building/address."""
        if not text:
            return set()

        lowered = text.lower()
        if not re.search(
            r"\b(condominio|via|viale|piazza|corso|largo|vicolo|strada|localit[aà])\b",
            lowered,
        ):
            return set()
        return self._anchor_tokens(lowered)

    def _check_type_compatibility(
        self,
        document_type: str,
        topic_class: str,
    ) -> float:
        """Check if document type is compatible with topic class."""
        compatibility_map = {
            "verbale_assemblea": {"meeting": 1.0, "general_administration": 0.5},
            "regolamento_condominiale": {"legal_matter": 1.0, "general_administration": 0.6},
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

    def _looks_like_specific_topic(self, topic: Topic) -> bool:
        """Check if a topic looks like a very specific/pointless topic (single bill, date, etc.).

        Returns True if the topic has a title that looks like a specific document
        rather than a stable matter — these should be penalized in retrieval.
        """
        title_lower = topic.title.lower()

        # Date-like patterns: contains a year or date
        if re.search(r"\b(19|20)\d{2}\b", title_lower):
            return True

        # Contains specific document identifiers
        if re.search(r"\b(fattura|bolletta|n\.|nr\.|num\.|numero)\s*\d", title_lower):
            return True

        # Very short titles that are just a name/entity (no context)
        if len(title_lower.split()) <= 3 and topic.topic_kind == "entity":
            return True

        # Contains "pagamento" or "versamento" (single payment)
        if re.search(r"\b(pagamento|versamento|rata)\b", title_lower):
            return True

        return False
