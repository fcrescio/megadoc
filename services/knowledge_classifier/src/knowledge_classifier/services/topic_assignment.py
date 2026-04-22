"""Topic assignment service."""

import logging

from sqlalchemy.orm import Session

from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.base import ChatMessage, LLMProvider
from knowledge_classifier.prompts import TOPIC_ASSIGNMENT_PROMPT
from knowledge_classifier.schemas import (
    ExtractedEntity,
    TopicAssignmentDecision,
    TopicCandidate,
    TopicClass,
)

logger = logging.getLogger(__name__)


class TopicAssignmentService:
    """Service for assigning documents to topics or proposing new topics."""

    def __init__(self, llm_provider: LLMProvider, db_session: Session):
        self.llm = llm_provider
        self.db = db_session
        self.settings = get_settings()

    def assign_topic(
        self,
        document_type_code: str | None,
        document_title: str | None,
        document_summary: str | None,
        entities: list[ExtractedEntity],
        candidates: list[TopicCandidate],
    ) -> TopicAssignmentDecision:
        """Decide topic assignment for a document.
        
        Args:
            document_type_code: Classified document type
            document_title: Document title
            document_summary: Document summary
            entities: Extracted entities
            candidates: Candidate topics from retrieval
            
        Returns:
            TopicAssignmentDecision with action and details
        """
        # Build topics list for prompt
        topics_list = self._format_topics_list(candidates)
        
        # Build entities list for prompt
        entities_list = self._format_entities_list(entities)
        
        prompt = TOPIC_ASSIGNMENT_PROMPT.format(
            topics_list=topics_list,
            document_type=document_type_code or "unknown",
            document_title=document_title or "Untitled",
            document_summary=document_summary or "No summary",
            entities_list=entities_list,
        )
        
        messages = [
            ChatMessage(role="system", content="You are a topic assignment expert."),
            ChatMessage(role="user", content=prompt),
        ]
        
        try:
            result, _ = self.llm.chat_with_json(
                messages,
                TopicAssignmentDecision,
                temperature=self.settings.llm_temperature,
            )
            return result
        except Exception as e:
            logger.error(f"LLM topic assignment failed: {e}")
            return self._heuristic_assignment(candidates, entities)

    def _format_topics_list(self, candidates: list[TopicCandidate]) -> str:
        """Format topics list for prompt."""
        if not candidates:
            return "No existing topics available."
        
        lines = []
        for i, candidate in enumerate(candidates[:10], 1):
            lines.append(
                f"{i}. [{candidate.topic_id}] {candidate.title} ({candidate.slug}) - Score: {candidate.score:.2f}"
            )
        return "\n".join(lines)

    def _format_entities_list(self, entities: list[ExtractedEntity]) -> str:
        """Format entities list for prompt."""
        if not entities:
            return "No entities extracted."
        
        lines = []
        for entity in entities[:15]:
            lines.append(
                f"- {entity.entity_type}: {entity.entity_value}"
            )
        return "\n".join(lines)

    def _heuristic_assignment(
        self,
        candidates: list[TopicCandidate],
        entities: list[ExtractedEntity],
    ) -> TopicAssignmentDecision:
        """Fallback heuristic-based topic assignment."""
        if not candidates:
            # No candidates, propose new topic
            return TopicAssignmentDecision(
                action="propose_new",
                topic_ids=[],
                assignment_roles=[],
                proposed_topic={
                    "proposed_slug": "new-topic",
                    "proposed_title": "New Topic",
                    "topic_class": TopicClass.OTHER.value,
                    "description": "No existing topics matched"
                },
                confidence=0.5,
                rationale="No existing topics available, proposing new topic"
            )
        
        # Check for strong match
        best = candidates[0]
        if best.score >= self.settings.confidence_threshold_topic:
            return TopicAssignmentDecision(
                action="assign_existing",
                topic_ids=[best.topic_id],
                assignment_roles=["primary"],
                proposed_topic=None,
                confidence=best.score,
                rationale=f"Strong match with topic: {best.title}"
            )
        
        # Check for multiple reasonable matches
        reasonable = [c for c in candidates if c.score >= 0.4]
        if len(reasonable) >= 2:
            return TopicAssignmentDecision(
                action="assign_multiple",
                topic_ids=[c.topic_id for c in reasonable[:3]],
                assignment_roles=["primary"] + ["secondary"] * (len(reasonable) - 1),
                proposed_topic=None,
                confidence=best.score * 0.9,
                rationale=f"Multiple reasonable matches found"
            )
        
        # Weak match - needs review
        if best.score >= 0.3:
            return TopicAssignmentDecision(
                action="needs_review",
                topic_ids=[best.topic_id],
                assignment_roles=["primary"],
                proposed_topic=None,
                confidence=best.score,
                rationale="Weak match, requires human review"
            )
        
        # No good match - propose new
        return TopicAssignmentDecision(
            action="propose_new",
            topic_ids=[],
            assignment_roles=[],
            proposed_topic={
                "proposed_slug": "review-required",
                "proposed_title": "Topic Review Required",
                "topic_class": TopicClass.OTHER.value,
                "description": "No suitable existing topic found"
            },
            confidence=0.3,
            rationale="No suitable existing topic, new topic proposal needed"
        )
