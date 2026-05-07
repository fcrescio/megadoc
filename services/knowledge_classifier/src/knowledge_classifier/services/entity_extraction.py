"""Entity extraction service."""

import logging

from sqlalchemy.orm import Session

from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.base import ChatMessage, LLMProvider
from knowledge_classifier.prompts import ENTITY_EXTRACTION_PROMPT
from knowledge_classifier.schemas import EntityExtractionResult
from knowledge_classifier.services.language import detect_document_language, output_language_instruction

logger = logging.getLogger(__name__)


class EntityExtractionService:
    """Service for extracting entities from documents."""

    def __init__(self, llm_provider: LLMProvider, db_session: Session):
        self.llm = llm_provider
        self.db = db_session
        self.settings = get_settings()

    def extract_entities(
        self,
        document_text: str,
        start_page: int = 1,
        end_page: int = 1,
        language_code: str | None = None,
    ) -> EntityExtractionResult:
        """Extract entities from document text.
        
        Args:
            document_text: Text content of the document
            start_page: Starting page number
            end_page: Ending page number
            
        Returns:
            EntityExtractionResult with extracted entities and summary
        """
        language_code = language_code or detect_document_language(document_text)
        # Truncate if too long
        max_length = 12000
        if len(document_text) > max_length:
            half = max_length // 2
            document_text = document_text[:half] + "\n...\n" + document_text[-half:]
        
        # Use replace instead of format to avoid conflicts with JSON in prompt
        prompt = (
            ENTITY_EXTRACTION_PROMPT
            .replace("{document_text}", document_text)
            .replace("{output_language_instruction}", output_language_instruction(language_code))
        )
        
        messages = [
            ChatMessage(role="system", content="You are an entity extraction expert."),
            ChatMessage(role="user", content=prompt),
        ]
        
        try:
            result, _ = self.llm.chat_with_json(
                messages,
                EntityExtractionResult,
                temperature=self.settings.llm_temperature,
            )
            # Add page info to entities
            for entity in result.entities:
                if entity.page_from is None:
                    entity.page_from = start_page
                if entity.page_to is None:
                    entity.page_to = end_page
            return result
        except Exception:
            logger.exception("LLM entity extraction failed")
            raise
