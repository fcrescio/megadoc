"""Pipeline strategy layer for routed scan processing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from common.db.models import OCRResult
    from knowledge_classifier.services.pipeline import KnowledgePipelineService


class BasePipelineStrategy:
    """Base strategy for routed scan processing."""

    pipeline_id = "general_pipeline"

    def postprocess(
        self,
        pipeline_service: KnowledgePipelineService,
        scan_unit: Any,
        document_units: list[Any],
        entity_results: dict[Any, Any],
        ocr_result: OCRResult,
    ) -> None:
        """Apply post-classification normalization for the selected family."""
        pipeline_service._consolidate_scan_topics(scan_unit, document_units, entity_results)
        pipeline_service._update_scan_assignment_confidence(scan_unit, document_units)


class GeneralPipelineStrategy(BasePipelineStrategy):
    """Fallback general-purpose pipeline."""

    pipeline_id = "general_pipeline"


class NormativePipelineStrategy(BasePipelineStrategy):
    """Strategy for regulations and other long-form normative scans."""

    pipeline_id = "normative_pipeline"

    def postprocess(
        self,
        pipeline_service: KnowledgePipelineService,
        scan_unit: Any,
        document_units: list[Any],
        entity_results: dict[Any, Any],
        ocr_result: OCRResult,
    ) -> None:
        super().postprocess(pipeline_service, scan_unit, document_units, entity_results, ocr_result)
        pipeline_service._consolidate_scan_semantics(scan_unit, document_units, entity_results, ocr_result)
        pipeline_service._update_scan_assignment_confidence(scan_unit, document_units)


class MeetingPipelineStrategy(BasePipelineStrategy):
    """Reserved strategy for meeting-oriented scans."""

    pipeline_id = "meeting_pipeline"


class FinancialPipelineStrategy(BasePipelineStrategy):
    """Reserved strategy for financial scans."""

    pipeline_id = "financial_pipeline"


class UtilityVendorPipelineStrategy(BasePipelineStrategy):
    """Reserved strategy for utility/vendor scans."""

    pipeline_id = "utility_vendor_pipeline"


class TechnicalAdminPipelineStrategy(BasePipelineStrategy):
    """Reserved strategy for technical/administrative scans."""

    pipeline_id = "technical_admin_pipeline"
