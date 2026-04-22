"""Tests for segmentation service."""

from knowledge_classifier.llm.mock import MockDeterministicProvider
from knowledge_classifier.services.segmentation import SegmentationService
from tests.knowledge.fixtures import (
    VERBALE_OCR_STRUCTURED,
    VERBALE_OCR_MARKDOWN,
    MIXED_OCR_STRUCTURED,
    MIXED_OCR_MARKDOWN,
)


def test_segmentation_single_document():
    """Test segmentation of a single document (verbale)."""
    # Mock session (not used in segmentation)
    class MockSession:
        pass
    
    llm = MockDeterministicProvider()
    service = SegmentationService(llm, MockSession())
    
    result = service.segment_ocr_result(
        ocr_structured=VERBALE_OCR_STRUCTURED,
        ocr_markdown=VERBALE_OCR_MARKDOWN,
        page_count=1,
    )
    
    assert len(result.segments) >= 1
    assert result.segments[0].start_page == 1
    assert result.segments[0].end_page == 1
    assert result.overall_confidence > 0


def test_segmentation_mixed_documents():
    """Test segmentation of mixed documents (verbale + rendiconto)."""
    class MockSession:
        pass
    
    llm = MockDeterministicProvider()
    service = SegmentationService(llm, MockSession())
    
    result = service.segment_ocr_result(
        ocr_structured=MIXED_OCR_STRUCTURED,
        ocr_markdown=MIXED_OCR_MARKDOWN,
        page_count=3,
    )
    
    # Should detect at least 1 segment, ideally 2
    assert len(result.segments) >= 1
    assert result.segments[0].start_page == 1
    assert result.segments[-1].end_page == 3


def test_segmentation_heuristic_boundaries():
    """Test heuristic boundary detection."""
    class MockSession:
        pass
    
    llm = MockDeterministicProvider()
    service = SegmentationService(llm, MockSession())
    
    # Test with clear boundary patterns
    structured = {
        "pages": [
            {"page_number": 1, "text": "VERBALE DI ASSEMBLEA\nTest content"},
            {"page_number": 2, "text": "RENDICONTO CONTABILE\nDifferent content"},
        ]
    }
    markdown = "# VERBALE\n\nTest\n\n# RENDICONTO\n\nDifferent"
    
    result = service.segment_ocr_result(
        ocr_structured=structured,
        ocr_markdown=markdown,
        page_count=2,
    )
    
    # Should detect boundary between page 1 and 2
    assert len(result.segments) >= 1
    assert result.overall_confidence > 0
