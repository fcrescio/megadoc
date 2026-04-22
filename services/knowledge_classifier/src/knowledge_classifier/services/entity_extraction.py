"""Entity extraction service."""

import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.base import ChatMessage, LLMProvider
from knowledge_classifier.prompts import ENTITY_EXTRACTION_PROMPT
from knowledge_classifier.schemas import EntityExtractionResult, ExtractedEntity

logger = logging.getLogger(__name__)


class EntityExtractionService:
    """Service for extracting entities from documents."""

    def __init__(self, llm_provider: LLMProvider, db_session: AsyncSession):
        self.llm = llm_provider
        self.db = db_session
        self.settings = get_settings()

    async def extract_entities(
        self,
        document_text: str,
        start_page: int = 1,
        end_page: int = 1,
    ) -> EntityExtractionResult:
        """Extract entities from document text.
        
        Args:
            document_text: Text content of the document
            start_page: Starting page number
            end_page: Ending page number
            
        Returns:
            EntityExtractionResult with extracted entities and summary
        """
        # Truncate if too long
        max_length = 12000
        if len(document_text) > max_length:
            half = max_length // 2
            document_text = document_text[:half] + "\n...\n" + document_text[-half:]
        
        prompt = ENTITY_EXTRACTION_PROMPT.format(document_text=document_text)
        
        messages = [
            ChatMessage(role="system", content="You are an entity extraction expert."),
            ChatMessage(role="user", content=prompt),
        ]
        
        try:
            result, _ = await self.llm.chat_with_json(
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
        except Exception as e:
            logger.error(f"LLM entity extraction failed: {e}")
            return self._heuristic_extraction(document_text, start_page, end_page)

    def _heuristic_extraction(
        self,
        text: str,
        start_page: int,
        end_page: int,
    ) -> EntityExtractionResult:
        """Fallback heuristic-based entity extraction."""
        entities: list[ExtractedEntity] = []
        
        # Extract dates
        date_patterns = [
            (r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", "data"),
            (r"\b(\d{1,2}\s+(?:gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+\d{4})\b", "data"),
        ]
        
        for pattern, entity_type in date_patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                entities.append(ExtractedEntity(
                    entity_type=entity_type,
                    entity_value=match.group(0),
                    normalized_value=match.group(0).lower().replace(" ", "_"),
                    confidence=0.7,
                    page_from=start_page,
                    page_to=end_page
                ))
        
        # Extract amounts
        amount_pattern = r"\b(\d{1,3}(?:[\s.]\d{3})*(?:,\d{2})?)\s*(?:€|euro|EUR)\b"
        for match in re.finditer(amount_pattern, text, re.IGNORECASE):
            entities.append(ExtractedEntity(
                entity_type="importo",
                entity_value=match.group(0),
                normalized_value=match.group(1).replace(".", "").replace(",", "."),
                confidence=0.8,
                page_from=start_page,
                page_to=end_page
            ))
        
        # Extract document numbers
        doc_num_pattern = r"\b(?:n(?:º|o)|numero)\s*[:\s]*(\d{3,})\b"
        for match in re.finditer(doc_num_pattern, text, re.IGNORECASE):
            entities.append(ExtractedEntity(
                entity_type="numero_documento",
                entity_value=match.group(1),
                normalized_value=f"doc_{match.group(1)}",
                confidence=0.6,
                page_from=start_page,
                page_to=end_page
            ))
        
        # Extract condominium names
        condo_pattern = r"\bcondominio\s+([A-Z][A-Za-zÀÉÌÒÙ\s]+?)(?:\s+(?:di|via|piazza)|$)"
        for match in re.finditer(condo_pattern, text, re.IGNORECASE):
            entities.append(ExtractedEntity(
                entity_type="condominio",
                entity_value=f"Condominio {match.group(1).strip()}",
                normalized_value="condominio_" + match.group(1).lower().strip().replace(" ", "_"),
                confidence=0.75,
                page_from=start_page,
                page_to=end_page
            ))
        
        return EntityExtractionResult(
            entities=entities,
            summary=text[:200] + "..." if len(text) > 200 else text
        )
