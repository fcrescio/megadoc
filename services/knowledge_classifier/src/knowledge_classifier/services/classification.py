"""Classification service for document type classification."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import DocumentType
from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.base import ChatMessage, LLMProvider
from knowledge_classifier.prompts import CLASSIFICATION_PROMPT
from knowledge_classifier.schemas import ClassificationResult

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
        
        # Truncate text if too long
        max_length = 15000
        if len(document_text) > max_length:
            # Keep beginning and end
            half = max_length // 2
            document_text = document_text[:half] + "\n...\n" + document_text[-half:]
        
        # Use replace instead of format to avoid conflicts with JSON in prompt
        prompt = CLASSIFICATION_PROMPT.replace("{document_text}", document_text)
        
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
        except Exception as e:
            logger.error(f"LLM classification failed: {e}")
            # Fallback to heuristic classification
            return self._heuristic_classification(document_text)

    def _get_active_document_types(self) -> list[DocumentType]:
        """Get all active document types from database."""
        result = self.db.execute(
            select(DocumentType).where(DocumentType.is_active == True)
        )
        return list(result.scalars().all())

    def _heuristic_classification(self, text: str) -> ClassificationResult:
        """Fallback heuristic-based classification."""
        text_lower = text.lower()
        
        # Simple keyword-based classification
        type_scores: dict[str, float] = {}
        
        type_patterns = {
            "verbale_assemblea": (
                ["verbale", "assemblea", "deliberazione", "presenti", "assenti"],
                0.8
            ),
            "rendiconto_contabile": (
                ["rendiconto", "bilancio", "contabile", "spese", "entrate"],
                0.75
            ),
            "fattura": (
                ["fattura", "fatt.", "n.", "data", "importo", "totale"],
                0.8
            ),
            "preventivo": (
                ["preventivo", "offerta", "prezzo", "stima"],
                0.75
            ),
            "bolletta": (
                ["bolletta", "fattura elettronica", "pagamento", "scadenza"],
                0.7
            ),
            "contratto": (
                ["contratto", "accordo", "parti", "firme", "clausole"],
                0.75
            ),
            "lettera": (
                ["spett.le", "gentile", "cordiali saluti", "distinti saluti"],
                0.6
            ),
            "allegato_tecnico": (
                ["allegato", "specifiche", "tecnico", "schede"],
                0.65
            ),
        }
        
        for type_code, (keywords, base_score) in type_patterns.items():
            matches = sum(1 for kw in keywords if kw in text_lower)
            if matches > 0:
                score = min(base_score * (matches / len(keywords)) * 1.5, 1.0)
                type_scores[type_code] = score
        
        if type_scores:
            primary_code = max(type_scores, key=type_scores.get)
            primary_score = type_scores[primary_code]
            
            keywords = type_patterns[primary_code][0]
            matched_keywords = [k for k in keywords if k in text_lower][:3]
            return ClassificationResult(
                primary_type={
                    "type_code": primary_code,
                    "confidence": primary_score,
                    "salient_features": matched_keywords
                },
                alternatives=[],
                rationale=f"Heuristic classification based on keyword matching"
            )
        
        # Default to "altro"
        return ClassificationResult(
            primary_type={
                "type_code": "altro",
                "confidence": 0.5,
                "salient_features": []
            },
            alternatives=[],
            rationale="No clear document type detected"
        )
