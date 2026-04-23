from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from common.config import Settings, get_settings


class PDFPreflightReport(BaseModel):
    valid_pdf: bool
    file_size_bytes: int
    page_count: int | None = None
    bytes_per_page: int | None = None
    encrypted: bool = False
    sampled_text_pages: int = 0
    sampled_text_chars: int = 0
    text_extractable: bool | None = None
    average_page_width: float | None = None
    average_page_height: float | None = None
    declared_rotations: dict[str, int] = Field(default_factory=dict)
    dominant_declared_rotation: int | None = None
    rotation_detector_backend: str | None = None
    detected_rotation: int | None = None
    detected_rotation_confidence: float | None = None
    flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class PDFPreflightService:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def analyze(self, source: Path) -> PDFPreflightReport:
        file_size_bytes = source.stat().st_size
        report = PDFPreflightReport(valid_pdf=True, file_size_bytes=file_size_bytes)

        if not self._settings.preflight_enabled:
            return report

        try:
            from pypdf import PdfReader
        except ImportError as exc:
            report.warnings.append("pypdf_not_available")
            report.error = "Preflight dependency pypdf is not installed."
            report.valid_pdf = False
            raise RuntimeError(report.error) from exc

        try:
            reader = PdfReader(str(source), strict=False)
        except Exception as exc:
            report.valid_pdf = False
            report.error = f"Malformed PDF: {exc}"
            report.flags.append("malformed_pdf")
            return report

        if reader.is_encrypted:
            report.valid_pdf = False
            report.encrypted = True
            report.error = "Encrypted PDF is not supported."
            report.flags.append("encrypted_pdf")
            return report

        page_count = len(reader.pages)
        report.page_count = page_count
        report.bytes_per_page = int(file_size_bytes / page_count) if page_count else None

        widths: list[float] = []
        heights: list[float] = []
        rotation_counts: dict[int, int] = {}
        sampled_text_chars = 0
        sampled_pages = self._sample_page_numbers(page_count)

        for index, page in enumerate(reader.pages):
            rotation = int(page.get("/Rotate", 0) or 0) % 360
            rotation_counts[rotation] = rotation_counts.get(rotation, 0) + 1

            media_box = getattr(page, "mediabox", None)
            if media_box is not None:
                try:
                    widths.append(float(media_box.width))
                    heights.append(float(media_box.height))
                except Exception:
                    report.warnings.append(f"page_box_unreadable:{index + 1}")

            if index + 1 in sampled_pages:
                try:
                    sampled_text = page.extract_text() or ""
                except Exception:
                    sampled_text = ""
                    report.warnings.append(f"text_extract_failed:{index + 1}")
                sampled_text_chars += len(sampled_text.strip())

        report.sampled_text_pages = len(sampled_pages)
        report.sampled_text_chars = sampled_text_chars
        report.text_extractable = sampled_text_chars > 0
        if widths:
            report.average_page_width = sum(widths) / len(widths)
        if heights:
            report.average_page_height = sum(heights) / len(heights)

        report.declared_rotations = {
            str(rotation): count for rotation, count in sorted(rotation_counts.items()) if count
        }
        non_zero_rotations = {rotation: count for rotation, count in rotation_counts.items() if rotation}
        if non_zero_rotations:
            report.flags.append("declared_rotation")
            report.dominant_declared_rotation = max(non_zero_rotations, key=non_zero_rotations.get)
            if len(non_zero_rotations) > 1:
                report.flags.append("mixed_declared_rotation")

        if report.bytes_per_page and report.bytes_per_page >= self._settings.preflight_heavy_scan_bytes_per_page:
            report.flags.append("heavy_scan")
        if report.text_extractable is False:
            report.flags.append("image_only_likely")

        self._annotate_rotation_detector(report)
        return report

    def _sample_page_numbers(self, page_count: int) -> set[int]:
        sample_count = min(max(self._settings.preflight_text_sample_pages, 1), max(page_count, 1))
        if page_count <= sample_count:
            return set(range(1, page_count + 1))

        positions = {
            1,
            page_count,
        }
        if sample_count == 2:
            return positions

        step = (page_count - 1) / (sample_count - 1)
        for sample_index in range(sample_count):
            positions.add(int(round(1 + sample_index * step)))
        return {page for page in positions if 1 <= page <= page_count}

    def _annotate_rotation_detector(self, report: PDFPreflightReport) -> None:
        backend = self._settings.rotation_detector_backend.strip().lower()
        if backend in {"", "none", "disabled"}:
            return

        report.rotation_detector_backend = backend
        if backend == "huggingface_rotdet":
            report.warnings.append("rotation_detector_not_enabled")
            report.warnings.append(
                "Hugging Face rotation detection requires an image renderer/inference runtime not wired yet."
            )
            if self._settings.rotation_detector_model_id:
                report.warnings.append(
                    f"rotation_detector_model:{self._settings.rotation_detector_model_id}"
                )
            return

        report.warnings.append(f"unknown_rotation_detector_backend:{backend}")
