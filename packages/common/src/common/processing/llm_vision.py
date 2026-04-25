import base64
import json
import logging
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from common.config import Settings
from common.domain.exceptions import ProcessingError
from common.domain.models import OCRResultModel
from common.processing.preflight import PDFPreflightReport

logger = logging.getLogger(__name__)


class VisionOCRBlockResult(BaseModel):
    block_type: Literal["heading", "paragraph", "list_item", "table", "caption", "other"] = "paragraph"
    text: str
    confidence: float | None = None


class VisionOCRPageResult(BaseModel):
    page_number: int
    plain_text: str
    markdown_text: str
    blocks: list[VisionOCRBlockResult] = Field(default_factory=list)
    confidence: float | None = None
    notes: list[str] = Field(default_factory=list)


class LLMVisionOCRService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def process(
        self,
        source: Path,
        preflight: PDFPreflightReport | None = None,
    ) -> OCRResultModel:
        try:
            import fitz
        except ImportError as exc:
            raise ProcessingError("PyMuPDF is required for llm_vision OCR backend.") from exc

        document = fitz.open(source)
        try:
            page_results: list[VisionOCRPageResult] = []
            usage_records: list[dict[str, Any]] = []
            for page_number in range(1, document.page_count + 1):
                image_data_url = self._render_page_data_url(fitz, source, page_number)
                page_result, usage = self._ocr_page(page_number, image_data_url)
                page_results.append(page_result)
                if usage:
                    usage_records.append(usage)
        finally:
            document.close()

        full_text = "\n\n".join(page.plain_text.strip() for page in page_results if page.plain_text.strip())
        markdown_text = "\n\n".join(page.markdown_text.strip() for page in page_results if page.markdown_text.strip())
        structured_pages = [self._page_to_structured(page_result) for page_result in page_results]
        average_confidence = None
        confidences = [page.confidence for page in page_results if page.confidence is not None]
        if confidences:
            average_confidence = sum(confidences) / len(confidences)

        confidence_summary: dict[str, Any] = {
            "llm_vision": {
                "model": self._settings.ocr_llm_vision_model,
                "page_count": len(page_results),
                "average_page_confidence": average_confidence,
                "render_scale": self._settings.ocr_llm_vision_render_scale,
            }
        }
        if usage_records:
            confidence_summary["llm_vision"]["usage"] = {
                "requests": len(usage_records),
                "total_prompt_tokens": sum(int(record.get("prompt_tokens", 0) or 0) for record in usage_records),
                "total_completion_tokens": sum(int(record.get("completion_tokens", 0) or 0) for record in usage_records),
                "total_tokens": sum(int(record.get("total_tokens", 0) or 0) for record in usage_records),
            }

        return OCRResultModel(
            engine_name="llm_vision",
            engine_version=self._settings.ocr_llm_vision_model,
            pipeline_version=self._settings.pipeline_version,
            full_text=full_text,
            markdown_text=markdown_text,
            structured_json={
                "pages": structured_pages,
                "backend": "llm_vision",
            },
            page_count=len(page_results),
            confidence_summary=confidence_summary,
        )

    def _ocr_page(self, page_number: int, image_data_url: str) -> tuple[VisionOCRPageResult, dict[str, Any] | None]:
        payload = self._build_payload(page_number, image_data_url, use_response_format=True)
        response = self._request(payload)
        if response is None:
            fallback_payload = self._build_payload(page_number, image_data_url, use_response_format=False)
            response = self._request(fallback_payload)
        if response is None:
            raise ProcessingError(f"llm_vision OCR failed for page {page_number}")

        raw_content = response["content"]
        usage = response["usage"]
        try:
            parsed = VisionOCRPageResult.model_validate_json(self._extract_json_text(raw_content))
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            raise ProcessingError(f"llm_vision OCR returned invalid JSON for page {page_number}") from exc
        return parsed, usage

    def _build_payload(self, page_number: int, image_data_url: str, use_response_format: bool) -> dict[str, Any]:
        schema = VisionOCRPageResult.model_json_schema()
        payload: dict[str, Any] = {
            "model": self._settings.ocr_llm_vision_model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an OCR engine. Extract only what is visible on the page. "
                        "Preserve headings, paragraphs, lists, and tables as markdown when possible. "
                        "Do not add explanations. Do not invent missing text."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                f"Page number: {page_number}\n"
                                "Return only valid JSON with fields: "
                                "page_number, plain_text, markdown_text, blocks, confidence, notes.\n"
                                "Use markdown_text to preserve the reading structure. "
                                "Use blocks in reading order. Keep notes short."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
            "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False},
            "max_tokens": self._settings.ocr_llm_vision_max_tokens,
        }
        if use_response_format:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "VisionOCRPageResult",
                    "schema": schema,
                },
            }
        return payload

    def _request(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._settings.ocr_llm_vision_api_key:
            headers["Authorization"] = f"Bearer {self._settings.ocr_llm_vision_api_key}"

        try:
            with httpx.Client(
                base_url=self._settings.ocr_llm_vision_endpoint.rstrip("/"),
                headers=headers,
                timeout=httpx.Timeout(self._settings.ocr_llm_vision_timeout),
            ) as client:
                response = client.post("/chat/completions", json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError:
            logger.exception("llm_vision_request_failed")
            return None

        try:
            choice = data["choices"][0]
            return {
                "content": choice["message"]["content"],
                "usage": data.get("usage"),
            }
        except (KeyError, IndexError, TypeError):
            logger.exception("llm_vision_response_invalid")
            return None

    def _render_page_data_url(self, fitz_module, source: Path, page_number: int) -> str:
        document = fitz_module.open(source)
        try:
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(
                matrix=fitz_module.Matrix(
                    self._settings.ocr_llm_vision_render_scale,
                    self._settings.ocr_llm_vision_render_scale,
                ),
                alpha=False,
            )
            png_bytes = pixmap.tobytes("png")
        finally:
            document.close()

        encoded = base64.b64encode(png_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _extract_json_text(self, content: str) -> str:
        cleaned = content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        if cleaned.startswith("{"):
            return cleaned
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            return cleaned[start:end + 1]
        raise ValueError("No JSON payload found in llm_vision response")

    def _page_to_structured(self, page_result: VisionOCRPageResult) -> dict[str, Any]:
        blocks = []
        source_blocks = page_result.blocks or [VisionOCRBlockResult(block_type="paragraph", text=page_result.plain_text)]
        for index, block in enumerate(source_blocks, start=1):
            blocks.append(
                {
                    "id": f"page-{page_result.page_number}-block-{index}",
                    "type": block.block_type,
                    "reading_order": index,
                    "text": block.text,
                    "metadata": {
                        "confidence": block.confidence,
                    },
                }
            )
        return {
            "page_number": page_result.page_number,
            "page_no": page_result.page_number,
            "text": page_result.plain_text,
            "markdown": page_result.markdown_text,
            "blocks": blocks,
            "tables": [],
            "figures": [],
            "metadata": {
                "confidence": page_result.confidence,
                "notes": page_result.notes,
            },
        }
