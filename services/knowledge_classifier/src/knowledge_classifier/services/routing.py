"""Routing service for choosing a scan processing pipeline."""

import logging
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from common.db.models import OCRResult
from knowledge_classifier.config import get_settings
from knowledge_classifier.llm.base import ChatMessage, LLMProvider
from knowledge_classifier.prompts import PIPELINE_ROUTING_PROMPT
from knowledge_classifier.services.language import detect_document_language, output_language_instruction

logger = logging.getLogger(__name__)


class PipelineFamily(str, Enum):
    """High-level families used by the scan router."""

    GENERAL = "general"
    NORMATIVE = "normative"
    MEETING = "meeting"
    FINANCIAL = "financial"
    UTILITY_VENDOR = "utility_vendor"
    TECHNICAL_ADMIN = "technical_admin"


class PipelineRoutingDecision(BaseModel):
    """Routing decision for a scan unit."""

    pipeline_id: Literal[
        "general_pipeline",
        "normative_pipeline",
        "meeting_pipeline",
        "financial_pipeline",
        "utility_vendor_pipeline",
        "technical_admin_pipeline",
    ]
    family: Literal[
        "general",
        "normative",
        "meeting",
        "financial",
        "utility_vendor",
        "technical_admin",
    ]
    confidence: float = Field(..., ge=0, le=1)
    rationale: str
    signals: list[str] = Field(default_factory=list)


class PipelineRouterService:
    """Choose the most appropriate pipeline family for a scan."""

    _PIPELINE_FAMILIES = {
        "general_pipeline": PipelineFamily.GENERAL.value,
        "normative_pipeline": PipelineFamily.NORMATIVE.value,
        "meeting_pipeline": PipelineFamily.MEETING.value,
        "financial_pipeline": PipelineFamily.FINANCIAL.value,
        "utility_vendor_pipeline": PipelineFamily.UTILITY_VENDOR.value,
        "technical_admin_pipeline": PipelineFamily.TECHNICAL_ADMIN.value,
    }

    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider
        self.settings = get_settings()

    def route_scan(self, ocr_result: OCRResult) -> PipelineRoutingDecision:
        """Route a scan by asking the LLM for a structured pipeline decision."""
        scan_text = self._scan_text(ocr_result)
        return self.route_text(scan_text)

    def route_text(self, text: str) -> PipelineRoutingDecision:
        """Route one document or segment by LLM semantic classification."""
        document_text = (text or "").strip()
        max_length = 15000
        if len(document_text) > max_length:
            half = max_length // 2
            document_text = document_text[:half] + "\n...\n" + document_text[-half:]

        language_code = detect_document_language(document_text)
        prompt = (
            PIPELINE_ROUTING_PROMPT
            .replace("{document_text}", document_text)
            .replace("{output_language_instruction}", output_language_instruction(language_code))
        )
        messages = [
            ChatMessage(role="system", content="You route document segments to processing pipelines."),
            ChatMessage(role="user", content=prompt),
        ]

        try:
            decision, _ = self.llm.chat_with_json(
                messages,
                PipelineRoutingDecision,
                temperature=self.settings.llm_temperature,
            )
        except Exception:
            logger.exception("LLM pipeline routing failed")
            raise

        expected_family = self._PIPELINE_FAMILIES[decision.pipeline_id]
        if decision.family != expected_family:
            decision.family = expected_family
        return decision

    def _scan_text(self, ocr_result: OCRResult) -> str:
        text = "\n".join(
            part
            for part in (
                ocr_result.markdown_text or "",
                ocr_result.full_text or "",
            )
            if part
        )
        return text[:30000]
