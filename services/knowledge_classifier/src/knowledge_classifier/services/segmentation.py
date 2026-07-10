"""Segmentation service for splitting scans into document units."""

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from common.application.page_artifacts import build_page_artifacts
from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.base import ChatMessage
from knowledge_classifier.llm.base import LLMProvider
from knowledge_classifier.prompts import SEGMENTATION_PROMPT
from knowledge_classifier.schemas import (
    PageRepresentation,
    SegmentCandidate,
    SegmentationResult,
)
from knowledge_classifier.services.language import detect_document_language, output_language_instruction

logger = logging.getLogger(__name__)

class SegmentationService:
    """Service for segmenting OCR results into document units."""

    def __init__(self, llm_provider: LLMProvider, db_session: Session):
        self.llm = llm_provider
        self.db = db_session
        self.settings = get_settings()

    def segment_ocr_result(
        self,
        ocr_structured: dict[str, Any],
        ocr_markdown: str,
        page_count: int,
    ) -> SegmentationResult:
        """Segment an OCR result into document units.
        
        Args:
            ocr_structured: Structured JSON from OCR
            ocr_markdown: Markdown text from OCR
            page_count: Total number of pages
            
        Returns:
            SegmentationResult with segments and boundaries
        """
        # Build page representations
        pages = self._build_page_representations(ocr_structured, ocr_markdown, page_count)
        
        if not pages:
            raise ValueError("No page data available for segmentation.")

        # Multi-page segmentation is a semantic decision: delegate it to the LLM.
        # Deterministic boundary rules are intentionally not used as an automatic
        # fallback because they caused keyword-driven splits on noisy scans.
        if len(pages) > 1:
            llm_result = self._segment_with_llm(pages)
            return llm_result
        
        # Single-page scans are the only solid deterministic case.
        return SegmentationResult(
            segments=[SegmentCandidate(
                start_page=1,
                end_page=page_count,
                confidence=0.9,
                rationale="Single page scan"
            )],
            overall_confidence=0.9,
            boundaries=[]
        )

    def _build_page_representations(
        self,
        structured: dict[str, Any],
        markdown: str,
        page_count: int,
    ) -> list[PageRepresentation]:
        """Build page representations from OCR data."""
        artifacts = build_page_artifacts(
            structured_json=structured,
            markdown_text=markdown,
            full_text=markdown,
            page_count=page_count,
        )
        return [
            PageRepresentation(
                page_number=artifact.page_number,
                text=artifact.markdown or artifact.text,
                headings=self._extract_headings(artifact.markdown or artifact.text),
                keywords=self._extract_keywords(artifact.markdown or artifact.text),
            )
            for artifact in artifacts
        ]

    def _extract_headings(self, text: str) -> list[str]:
        """Extract potential headings from text."""
        headings = []
        
        # Markdown headings
        for match in re.finditer(r"^#{1,3}\s+(.+)$", text, re.MULTILINE):
            headings.append(match.group(1).strip())
        
        # Uppercase lines (potential titles)
        for match in re.finditer(r"^([A-ZÀÉÌÒÙ]{3,}(?:\s+[A-ZÀÉÌÒÙ]+)+)$", text, re.MULTILINE):
            line = match.group(1).strip()
            if len(line) < 200 and line not in headings:
                headings.append(line)
        
        return headings[:10]  # Limit to top 10

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract keywords from text."""
        keywords = []
        
        # Document type keywords
        doc_keywords = [
            "verbale", "assemblea", "rendiconto", "fattura", "preventivo",
            "bolletta", "contratto", "allegato", "deliberazione", "spese",
            "condominio", "amministratore", "fornitore"
        ]
        
        text_lower = text.lower()
        for kw in doc_keywords:
            if kw in text_lower:
                keywords.append(kw)
        
        return keywords[:10]

    def _segment_with_llm(self, pages: list[PageRepresentation]) -> SegmentationResult:
        """Use LLM to segment ambiguous documents."""
        # Build pages content string
        pages_content = "\n\n".join([
            f"=== Page {p.page_number} ===\n{p.text[:2000]}"
            for p in pages[:10]  # Limit to first 10 pages for context
        ])
        language_code = detect_document_language(pages_content)

        # Use replace instead of format to avoid conflicts with JSON in prompt
        prompt = (
            SEGMENTATION_PROMPT
            .replace("{pages_content}", pages_content)
            .replace("{output_language_instruction}", output_language_instruction(language_code))
        )
        
        messages = [
            ChatMessage(role="system", content="You are a document segmentation expert."),
            ChatMessage(role="user", content=prompt),
        ]
        
        try:
            result, _ = self.llm.chat_with_json(
                messages,
                SegmentationResult,
                temperature=self.settings.llm_temperature,
            )
            return result
        except Exception:
            logger.exception("LLM segmentation failed")
            raise
