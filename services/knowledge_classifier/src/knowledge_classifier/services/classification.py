"""Classification service for document type classification."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import DocumentType
from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.base import ChatMessage, LLMProvider
from knowledge_classifier.prompts import CLASSIFICATION_PROMPT
from knowledge_classifier.schemas import ClassificationResult
from knowledge_classifier.services.language import detect_document_language, output_language_instruction

logger = logging.getLogger(__name__)


class ClassificationService:
    """Service for classifying document units into document types."""

    def __init__(self, llm_provider: LLMProvider, db_session: Session):
        self.llm = llm_provider
        self.db = db_session
        self.settings = get_settings()

    def classify_document(
        self,
        document_text: str,
        available_types: list[DocumentType] | None = None,
        language_code: str | None = None,
    ) -> ClassificationResult:
        """Classify a document into a document type.
        
        Args:
            document_text: Text content of the document
            available_types: List of available document types (defaults to all active)
            
        Returns:
            ClassificationResult with primary type and alternatives
        """
        if available_types is None:
            available_types = self._get_active_document_types()
        language_code = language_code or detect_document_language(document_text)
        
        # Truncate text if too long
        max_length = 15000
        if len(document_text) > max_length:
            # Keep beginning and end
            half = max_length // 2
            document_text = document_text[:half] + "\n...\n" + document_text[-half:]
        
        # Use replace instead of format to avoid conflicts with JSON in prompt
        prompt = (
            CLASSIFICATION_PROMPT
            .replace("{document_text}", document_text)
            .replace("{output_language_instruction}", output_language_instruction(language_code))
        )
        
        messages = [
            ChatMessage(role="system", content="You are a document classification expert."),
            ChatMessage(role="user", content=prompt),
        ]
        
        try:
            result, _ = self.llm.chat_with_json(
                messages,
                ClassificationResult,
                temperature=self.settings.llm_temperature,
            )
            return result
        except Exception:
            logger.exception("LLM classification failed")
            raise

    def _get_active_document_types(self) -> list[DocumentType]:
        """Get all active document types from database."""
        result = self.db.execute(
            select(DocumentType).where(DocumentType.is_active == True)
        )
        return list(result.scalars().all())
