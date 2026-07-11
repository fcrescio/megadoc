from pathlib import Path

from common.config import Settings
from common.processing.orientation import OrientationPreprocessResult, OrientationPreprocessService
from common.processing.preflight import PDFPreflightReport


class StubOrientationService(OrientationPreprocessService):
    def __init__(self, settings: Settings, detections: list[dict], normalized_path: Path | None = None) -> None:
        super().__init__(settings)
        self._detections = detections
        self._normalized_path = normalized_path

    def _detect_page_orientations(
        self, source: Path, preflight: PDFPreflightReport | None, page_numbers: list[int] | None = None
    ) -> list[dict]:
        return list(self._detections)

    def _rotate_pdf(
        self, source: Path, rotation: int, *, page_rotations=None, reverse_page_order: bool = False
    ) -> Path:
        self.reverse_page_order = reverse_page_order
        self.page_rotations = page_rotations
        return self._normalized_path or source.with_name(f"{source.stem}.normalized-{rotation}.pdf")


def test_orientation_preprocess_applies_consensus_rotation(tmp_path) -> None:
    service = StubOrientationService(
        Settings(
            ROTATION_DETECTOR_BACKEND="paddle_doc_orientation",
            ROTATION_DETECTOR_MIN_CONFIDENCE=0.8,
            ROTATION_DETECTOR_MIN_CONSENSUS=0.75,
        ),
        detections=[
            {"page_number": 1, "rotation": 180, "confidence": 0.95},
            {"page_number": 2, "rotation": 180, "confidence": 0.93},
            {"page_number": 3, "rotation": 180, "confidence": 0.91},
            {"page_number": 4, "rotation": 0, "confidence": 0.99},
        ],
        normalized_path=tmp_path / "normalized.pdf",
    )

    result = service.preprocess(
        tmp_path / "input.pdf",
        PDFPreflightReport(valid_pdf=True, file_size_bytes=1234, page_count=4),
    )

    assert isinstance(result, OrientationPreprocessResult)
    assert result.normalized_path == tmp_path / "normalized.pdf"
    assert result.metadata["applied"] is True
    assert result.metadata["rotation_applied"] == 180
    assert result.metadata["page_order_reversed"] is False
    assert result.metadata["mixed_orientation"] is True
    assert result.metadata["page_rotations"] == {"1": 180, "2": 180, "3": 180, "4": 0}


def test_orientation_preprocess_reverses_page_order_for_full_180_stack(tmp_path) -> None:
    service = StubOrientationService(
        Settings(
            ROTATION_DETECTOR_BACKEND="paddle_doc_orientation",
            ROTATION_DETECTOR_MIN_CONFIDENCE=0.8,
            ROTATION_DETECTOR_MIN_CONSENSUS=0.75,
            ROTATION_REVERSE_PAGE_ORDER_ON_180=True,
        ),
        detections=[
            {"page_number": 1, "rotation": 180, "confidence": 0.95},
            {"page_number": 5, "rotation": 180, "confidence": 0.93},
            {"page_number": 10, "rotation": 180, "confidence": 0.91},
            {"page_number": 14, "rotation": 180, "confidence": 0.92},
        ],
        normalized_path=tmp_path / "normalized.pdf",
    )

    result = service.preprocess(
        tmp_path / "input.pdf",
        PDFPreflightReport(valid_pdf=True, file_size_bytes=1234, page_count=14),
    )

    assert isinstance(result, OrientationPreprocessResult)
    assert result.metadata["rotation_applied"] == 180
    assert result.metadata["page_order_reversed"] is True
    assert service.reverse_page_order is True
    assert result.metadata["review_pages"] == []
    assert result.metadata["inferred_pages"] == [2, 3, 4, 6, 7, 8, 9, 11, 12, 13]


def test_orientation_preprocess_applies_per_page_rotation_when_consensus_is_weak(tmp_path) -> None:
    service = StubOrientationService(
        Settings(
            ROTATION_DETECTOR_BACKEND="paddle_doc_orientation",
            ROTATION_DETECTOR_MIN_CONFIDENCE=0.8,
            ROTATION_DETECTOR_MIN_CONSENSUS=0.75,
        ),
        detections=[
            {"page_number": 1, "rotation": 180, "confidence": 0.95},
            {"page_number": 2, "rotation": 90, "confidence": 0.93},
            {"page_number": 3, "rotation": 180, "confidence": 0.91},
            {"page_number": 4, "rotation": 90, "confidence": 0.91},
        ],
    )

    result = service.preprocess(
        tmp_path / "input.pdf",
        PDFPreflightReport(valid_pdf=True, file_size_bytes=1234, page_count=4),
    )

    assert isinstance(result, OrientationPreprocessResult)
    assert result.normalized_path is not None
    assert result.metadata["applied"] is True
    assert result.metadata["rotation_applied"] is None
    assert result.metadata["mixed_orientation"] is True
    assert service.page_rotations == {1: 180, 2: 90, 3: 180, 4: 90}


def test_orientation_preprocess_marks_low_confidence_pages_for_review(tmp_path) -> None:
    service = StubOrientationService(
        Settings(
            ROTATION_DETECTOR_BACKEND="paddle_doc_orientation",
            ROTATION_DETECTOR_MIN_CONFIDENCE=0.8,
            ROTATION_DETECTOR_MIN_CONSENSUS=0.75,
        ),
        detections=[
            {"page_number": 1, "rotation": 180, "confidence": 0.95},
            {"page_number": 2, "rotation": 180, "confidence": 0.60},
            {"page_number": 3, "rotation": 180, "confidence": 0.91},
            {"page_number": 4, "rotation": 180, "confidence": 0.93},
        ],
    )

    result = service.preprocess(
        tmp_path / "input.pdf",
        PDFPreflightReport(valid_pdf=True, file_size_bytes=1234, page_count=4),
    )

    assert result.metadata["review_pages"] == [2]
    assert result.metadata["page_rotations"]["2"] == 180
    assert result.metadata["page_order_reversed"] is False


def test_orientation_preprocess_skips_when_declared_rotation_exists(tmp_path) -> None:
    service = StubOrientationService(
        Settings(ROTATION_DETECTOR_BACKEND="paddle_doc_orientation"),
        detections=[{"page_number": 1, "rotation": 180, "confidence": 0.99}],
    )

    result = service.preprocess(
        tmp_path / "input.pdf",
        PDFPreflightReport(
            valid_pdf=True,
            file_size_bytes=1234,
            page_count=1,
            dominant_declared_rotation=180,
        ),
    )

    assert isinstance(result, OrientationPreprocessResult)
    assert result.normalized_path is None
    assert result.metadata["reason"] == "declared_rotation_present"
