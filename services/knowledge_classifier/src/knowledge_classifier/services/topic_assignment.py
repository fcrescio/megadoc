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
)
from knowledge_classifier.services.language import detect_document_language, output_language_instruction

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
        language_code: str | None = None,
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
        language_code = language_code or detect_document_language(
            " ".join(part for part in [document_title or "", document_summary or ""] if part).strip()
        )
        # Build topics list for prompt
        topics_list = self._format_topics_list(candidates, language_code)
        
        # Build entities list for prompt
        entities_list = self._format_entities_list(entities, language_code)
        
        # Use replace instead of format to avoid conflicts with JSON in prompt
        prompt = (TOPIC_ASSIGNMENT_PROMPT
            .replace("{topics_list}", topics_list)
            .replace("{document_type}", document_type_code or "unknown")
            .replace("{document_title}", document_title or ("Senza titolo" if language_code == "it" else "Untitled"))
            .replace("{document_summary}", document_summary or ("Nessun riassunto disponibile" if language_code == "it" else "No summary"))
            .replace("{entities_list}", entities_list)
            .replace("{output_language_instruction}", output_language_instruction(language_code)))
        
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
        except Exception:
            logger.exception("LLM topic assignment failed")
            raise

    def _format_topics_list(self, candidates: list[TopicCandidate], language_code: str) -> str:
        """Format topics list for prompt."""
        if not candidates:
            return "Nessun topic esistente disponibile." if language_code == "it" else "No existing topics available."
        
        lines = []
        for i, candidate in enumerate(candidates[:10], 1):
            lines.append(
                f"{i}. [{candidate.topic_id}] {candidate.title} ({candidate.slug}) - Score: {candidate.score:.2f}"
            )
        return "\n".join(lines)

    def _format_entities_list(self, entities: list[ExtractedEntity], language_code: str) -> str:
        """Format entities list for prompt."""
        if not entities:
            return "Nessuna entità estratta." if language_code == "it" else "No entities extracted."
        
        lines = []
        for entity in entities[:15]:
            lines.append(
                f"- {entity.entity_type}: {entity.entity_value}"
            )
        return "\n".join(lines)
