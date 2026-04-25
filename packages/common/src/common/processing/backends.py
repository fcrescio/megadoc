import importlib.metadata
from contextlib import contextmanager
from pathlib import Path

from common.config import Settings, get_settings
from common.domain.exceptions import ProcessingError
from common.domain.models import OCRResultModel
from common.processing.llm_vision import LLMVisionOCRService
from common.processing.preflight import PDFPreflightReport


class DocumentProcessingBackend:
    def process(self, source: Path, preflight: PDFPreflightReport | None = None) -> OCRResultModel:
        raise NotImplementedError


class FakeProcessingBackend(DocumentProcessingBackend):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def process(self, source: Path, preflight: PDFPreflightReport | None = None) -> OCRResultModel:
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
    _warmup_lock_path = Path("/tmp/megadoc-docling-init.lock")
    _warmup_ready_path = Path("/tmp/megadoc-docling-init.ready")

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def process(self, source: Path, preflight: PDFPreflightReport | None = None) -> OCRResultModel:
        if self._warmup_ready_path.exists():
            return self._convert(source)

        with self._warmup_lock():
            if self._warmup_ready_path.exists():
                return self._convert(source)

            result = self._convert(source)
            self._warmup_ready_path.touch()
            return result

    def _convert(self, source: Path) -> OCRResultModel:
        try:
            from docling.document_converter import DocumentConverter
            from docling.document_converter import PdfFormatOption
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import (
                AcceleratorOptions,
                PdfPipelineOptions,
                RapidOcrOptions,
            )
        except ImportError as exc:
            raise ProcessingError("Docling is not installed in the runtime image.") from exc

        pipeline_options = PdfPipelineOptions(
            accelerator_options=AcceleratorOptions(
                device=self._settings.ocr_accelerator_device,
                num_threads=self._settings.ocr_accelerator_num_threads,
            ),
            ocr_options=RapidOcrOptions(
                backend=self._settings.ocr_rapidocr_backend,
            ),
        )
        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(
                    pipeline_options=pipeline_options,
                )
            }
        )
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

    @contextmanager
    def _warmup_lock(self):
        self._warmup_lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._warmup_lock_path.open("a+b") as handle:
            try:
                import fcntl
            except ImportError as exc:
                raise ProcessingError("fcntl is required for serialized Docling warmup.") from exc

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def get_processing_backend(settings: Settings | None = None) -> DocumentProcessingBackend:
    app_settings = settings or get_settings()
    if app_settings.ocr_backend == "fake":
        return FakeProcessingBackend(app_settings)
    if app_settings.ocr_backend == "llm_vision":
        return LLMVisionProcessingBackend(app_settings)
    return DoclingProcessingBackend(app_settings)


class LLMVisionProcessingBackend(DocumentProcessingBackend):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service = LLMVisionOCRService(settings)

    def process(self, source: Path, preflight: PDFPreflightReport | None = None) -> OCRResultModel:
        return self._service.process(source, preflight=preflight)
