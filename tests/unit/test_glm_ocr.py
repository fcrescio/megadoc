import pytest

from common.config import Settings
from common.domain.exceptions import ProcessingError
from common.processing.glm_ocr import GLMOCRService, structured_glm_page
from api.main import _ingestion_queue_for_backend


def test_glm_retains_table_html_and_page_evidence():
    markdown = 'Testo\n<table><tr><td rowspan="2">Acqua &amp; gas</td><td>12,30</td></tr></table>'
    page = structured_glm_page(3, markdown)
    assert page["markdown"] == markdown
    assert page["tables"][0]["page_number"] == 3
    assert page["tables"][0]["cells"][0]["html"] == markdown.split("\n")[1]
    assert _ingestion_queue_for_backend(Settings(OCR_BACKEND="glm_ocr"), None) == "ingestion_llm_vision"


def test_glm_rejects_truncated_generation(monkeypatch, valid_pdf_path):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}

    monkeypatch.setattr("httpx.Client.post", lambda *args, **kwargs: Response())
    with pytest.raises(ProcessingError, match="truncated"):
        GLMOCRService(Settings()).process(valid_pdf_path)
