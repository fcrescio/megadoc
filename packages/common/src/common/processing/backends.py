import importlib.metadata
from pathlib import Path

from common.config import Settings, get_settings
from common.domain.exceptions import ProcessingError
from common.domain.models import OCRResultModel


class DocumentProcessingBackend:
    def process(self, source: Path) -> OCRResultModel:
        raise NotImplementedError


class FakeProcessingBackend(DocumentProcessingBackend):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def process(self, source: Path) -> OCRResultModel:
        text = f"Fake OCR output for {source.name}"
        structured = {
            "pages": [
                {
                    "page_number": 1,
                    "blocks": [
                        {
                            "id": "block-1",
                            "type": "paragraph",
                            "reading_order": 1,
                            "text": text,
                        }
                    ],
                    "tables": [],
                    "figures": [],
                }
            ]
        }
        return OCRResultModel(
            engine_name="fake",
            engine_version="1.0",
            pipeline_version=self._settings.pipeline_version,
            full_text=text,
            markdown_text=f"# OCR Result\n\n{text}",
            structured_json=structured,
            page_count=1,
            confidence_summary={"mode": "fake"},
        )


class DoclingProcessingBackend(DocumentProcessingBackend):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def process(self, source: Path) -> OCRResultModel:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as exc:
            raise ProcessingError("Docling is not installed in the runtime image.") from exc

        converter = DocumentConverter()
        result = converter.convert(source, raises_on_error=True)
        if result.document is None:
            raise ProcessingError("Docling returned no document.")
        document = result.document
        full_text = document.export_to_text()
        markdown = document.export_to_markdown()
        structured = document.export_to_dict()
        page_count = len(structured.get("pages", [])) or 1
        return OCRResultModel(
            engine_name="docling",
            engine_version=importlib.metadata.version("docling"),
            pipeline_version=self._settings.pipeline_version,
            full_text=full_text,
            markdown_text=markdown,
            structured_json=structured,
            page_count=page_count,
            confidence_summary=None,
        )


def get_processing_backend(settings: Settings | None = None) -> DocumentProcessingBackend:
    app_settings = settings or get_settings()
    if app_settings.ocr_backend == "fake":
        return FakeProcessingBackend(app_settings)
    return DoclingProcessingBackend(app_settings)

