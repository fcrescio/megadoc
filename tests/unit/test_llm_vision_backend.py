from pathlib import Path
from types import SimpleNamespace

from common.config import Settings
from common.processing.llm_vision import LLMVisionOCRService, VisionOCRPageResult


class StubLLMVisionOCRService(LLMVisionOCRService):
    def _render_page_data_url(self, fitz_module, source: Path, page_number: int) -> str:
        return f"data:image/png;base64,page-{page_number}"

    def _ocr_page(self, page_number: int, image_data_url: str):
        return (
            VisionOCRPageResult(
                page_number=page_number,
                plain_text=f"plain text {page_number}",
                markdown_text=f"# Page {page_number}\n\nplain text {page_number}",
                confidence=0.9,
            ),
            {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        )


def test_llm_vision_service_builds_docling_compatible_result(monkeypatch, tmp_path: Path) -> None:
    fake_document = SimpleNamespace(page_count=2, close=lambda: None)
    fake_fitz = SimpleNamespace(open=lambda source: fake_document)
    monkeypatch.setitem(__import__("sys").modules, "fitz", fake_fitz)

    service = StubLLMVisionOCRService(Settings())

    result = service.process(tmp_path / "doc.pdf")

    assert result.engine_name == "llm_vision"
    assert result.page_count == 2
    assert "plain text 1" in result.full_text
    assert "pages" in result.structured_json
    assert result.structured_json["pages"][0]["text"] == "plain text 1"
    assert result.confidence_summary["llm_vision"]["usage"]["total_tokens"] == 60
