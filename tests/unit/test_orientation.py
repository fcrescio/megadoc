from pathlib import Path

from common.config import Settings
from common.processing.orientation import OrientationPreprocessResult, OrientationPreprocessService
from common.processing.preflight import PDFPreflightReport


class StubOrientationService(OrientationPreprocessService):
    def __init__(self, settings: Settings, detections: list[dict], normalized_path: Path | None = None) -> None:
        super().__init__(settings)
        self._detections = detections
        self._normalized_path = normalized_path

    def _detect_page_orientations(self, source: Path, preflight: PDFPreflightReport | None) -> list[dict]:
        return list(self._detections)

    def _rotate_pdf(self, source: Path, rotation: int) -> Path:
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


def test_orientation_preprocess_skips_when_consensus_is_weak(tmp_path) -> None:
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
    assert result.normalized_path is None
    assert result.metadata["applied"] is False
    assert result.metadata["reason"] == "insufficient_consensus"


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
