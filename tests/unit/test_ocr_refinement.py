from pathlib import Path

from common.config import Settings
from common.domain.models import OCRResultModel
from common.processing.preflight import PDFPreflightReport
from common.processing.refinement import OCRRefinementPageResult, OCRRefinementService


class StubRefinementService(OCRRefinementService):
    def _render_page_data_url(self, fitz_module, source: Path, page_number: int) -> str | None:
        return f"data:image/png;base64,page-{page_number}"

    def _refine_page(self, candidate, image_data_url: str) -> OCRRefinementPageResult | None:
        return OCRRefinementPageResult(
            page_number=candidate.page_number,
            refined_text=f"REFINED::{candidate.page_number}",
            confidence=0.91,
            notes=["spacing repaired"],
        )


def _ocr_result() -> OCRResultModel:
    return OCRResultModel(
        engine_name="docling",
        engine_version="1",
        pipeline_version="v1",
        full_text="full",
        markdown_text="md",
        structured_json={
            "pages": [
                {
                    "page_number": 1,
                    "blocks": [
                        {"reading_order": 1, "text": "ClienteCRESCIOLI TotaleVendita Acconto Whirlpool"},
                    ],
                },
                {
                    "page_number": 2,
                    "blocks": [
                        {"reading_order": 1, "text": "Testo regolare con spazi e struttura normale."},
                    ],
                },
                {
                    "page_number": 3,
                    "blocks": [
                        {"reading_order": 1, "text": "MemoriadispesaPagamentoCONTANTIUNIEUROImporto"},
                    ],
                },
            ]
        },
        page_count=3,
        confidence_summary=None,
    )


def test_refinement_selects_noisy_pages_and_builds_payload(monkeypatch, tmp_path) -> None:
    settings = Settings(
        OCR_REFINEMENT_ENABLED=True,
        OCR_REFINEMENT_MAX_PAGES=2,
        OCR_REFINEMENT_MIN_PAGE_SCORE=0.2,
    )
    service = StubRefinementService(settings)
    monkeypatch.setitem(__import__("sys").modules, "fitz", object())

    result = service.refine(
        tmp_path / "dummy.pdf",
        _ocr_result(),
        PDFPreflightReport(
            valid_pdf=True,
            file_size_bytes=1_500_000,
            page_count=3,
            bytes_per_page=500_000,
            text_extractable=False,
            flags=["heavy_scan", "image_only_likely"],
        ),
    )

    assert result is not None
    assert sorted(result["selected_pages"]) == [1, 3]
    assert result["refined_page_count"] == 2
    assert {entry["refined_text"] for entry in result["page_results"]} == {
        "REFINED::1",
        "REFINED::3",
    }
    assert "REFINED::3" in result["refined_full_text"]


def test_refinement_skips_when_disabled(tmp_path) -> None:
    service = OCRRefinementService(Settings(OCR_REFINEMENT_ENABLED=False))
    result = service.refine(tmp_path / "dummy.pdf", _ocr_result(), None)
    assert result is None
