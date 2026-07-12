"""Tests for segmentation service."""

from knowledge_classifier.llm.mock import MockDeterministicProvider
from knowledge_classifier.schemas import SegmentBoundary, SegmentCandidate, SegmentationResult
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


def test_segmentation_uses_llm_for_multi_page_boundaries():
    """Test LLM-driven boundary detection for multi-page scans."""
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
    
    # Multi-page boundary detection is delegated to the LLM mock.
    assert len(result.segments) == 2
    assert result.boundaries
    assert result.overall_confidence > 0


def test_segmentation_windows_cover_long_scans_without_truncation():
    class WindowProvider:
        def chat_with_json(self, messages, response_model, temperature=0.0):
            content = messages[-1].content
            page_numbers = [
                int(line.removeprefix("=== Page ").removesuffix(" ==="))
                for line in content.splitlines()
                if line.startswith("=== Page ")
            ]
            start, end = min(page_numbers), max(page_numbers)
            boundary = start + 4
            segments = [SegmentCandidate(
                start_page=start,
                end_page=min(boundary, end),
                confidence=0.9,
                rationale="First document",
            )]
            boundaries = []
            if boundary < end:
                segments.append(SegmentCandidate(
                    start_page=boundary + 1,
                    end_page=end,
                    confidence=0.9,
                    rationale="Second document",
                ))
                boundaries.append(SegmentBoundary(
                    page_before=boundary,
                    page_after=boundary + 1,
                    confidence=0.9,
                    rationale="Document reset",
                ))
            return SegmentationResult(
                segments=segments,
                overall_confidence=0.9,
                boundaries=boundaries,
            ), {}

    service = SegmentationService(WindowProvider(), object())
    structured = {
        "pages": [
            {"page_number": page, "text": f"Page {page}"}
            for page in range(1, 35)
        ]
    }

    result = service.segment_ocr_result(structured, "", 34)

    assert result.segments[0].start_page == 1
    assert result.segments[-1].end_page == 34
    assert all(
        current.end_page + 1 == following.start_page
        for current, following in zip(result.segments, result.segments[1:])
    )
