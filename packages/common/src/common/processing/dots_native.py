import base64
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from common.config import Settings
from common.domain.exceptions import ProcessingError
from common.domain.models import OCRResultModel
from common.processing.preflight import PDFPreflightReport

logger = logging.getLogger(__name__)

DOTS_LAYOUT_PROMPT = """Please output the layout information from the PDF image, including each layout element's bbox, its category, and the corresponding text content within the bbox.

1. Bbox format: [x1, y1, x2, y2]

2. Layout Categories: The possible categories are ['Caption', 'Footnote', 'Formula', 'List-item', 'Page-footer', 'Page-header', 'Picture', 'Section-header', 'Table', 'Text', 'Title'].

3. Text Extraction & Formatting Rules:
- Picture: For the 'Picture' category, the text field should be omitted.
- Formula: Format its text as LaTeX.
- Table: Format its text as HTML.
- All Others (Text, Title, etc.): Format their text as Markdown.

4. Constraints:
- The output text must be the original text from the image, with no translation.
- All layout elements must be sorted according to human reading order.

5. Final Output: The entire output must be a single JSON object."""

DOTS_OCR_PROMPT = "Extract the text content from this image."


class DotsNativeOCRService:
    _SPARSE_PAGE_MEAN_THRESHOLD = 243.0
    _SPARSE_PAGE_DARK220_THRESHOLD = 0.02

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
            raise ProcessingError("PyMuPDF is required for dots_native OCR backend.") from exc

        document = fitz.open(source)
        try:
            page_structures: list[dict[str, Any]] = []
            usage_records: list[dict[str, Any]] = []
            page_markdown: list[str] = []
            page_texts: list[str] = []

            for page_number in range(1, document.page_count + 1):
                page_result = self._process_page(source, page_number)
                page_structures.append(page_result["page"])
                page_texts.append(page_result["page"]["text"])
                page_markdown.append(page_result["page"]["markdown"])
                usage_records.extend(page_result["usages"])
        finally:
            document.close()

        confidence_summary: dict[str, Any] = {
            "dots_native": {
                "model": self._settings.ocr_dots_native_model,
                "page_count": len(page_structures),
                "render_scale": self._settings.ocr_dots_native_render_scale,
            }
        }
        if usage_records:
            confidence_summary["dots_native"]["usage"] = {
                "requests": len(usage_records),
                "total_prompt_tokens": sum(int(record.get("prompt_tokens", 0) or 0) for record in usage_records),
                "total_completion_tokens": sum(
                    int(record.get("completion_tokens", 0) or 0) for record in usage_records
                ),
                "total_tokens": sum(int(record.get("total_tokens", 0) or 0) for record in usage_records),
            }
        confidence_summary["dots_native"]["fallback_to_ocr_pages"] = [
            page["page_number"]
            for page in page_structures
            if page.get("metadata", {}).get("mode") == "ocr"
        ]
        confidence_summary["dots_native"]["empty_pages"] = [
            page["page_number"]
            for page in page_structures
            if page.get("metadata", {}).get("mode") == "empty"
        ]

        return OCRResultModel(
            engine_name="dots_native",
            engine_version=self._settings.ocr_dots_native_model,
            pipeline_version=self._settings.pipeline_version,
            full_text="\n\n".join(text.strip() for text in page_texts if text.strip()),
            markdown_text="\n\n".join(markdown.strip() for markdown in page_markdown if markdown.strip()),
            structured_json={"pages": page_structures, "backend": "dots_native"},
            page_count=len(page_structures),
            confidence_summary=confidence_summary,
        )

    def _process_page(self, source: Path, page_number: int) -> dict[str, Any]:
        usages: list[dict[str, Any]] = []
        sparse_candidate: dict[str, Any] | None = None

        for candidate in self._page_render_candidates():
            rendered = self._render_page_candidate(
                source,
                page_number,
                scale=candidate["scale"],
                rotation=candidate["rotation"],
            )
            page_result = self._process_rendered_page(page_number, rendered)
            usages.extend(page_result["usages"])

            if page_result["page"] is not None:
                page = page_result["page"]
                metadata = dict(page.get("metadata") or {})
                metadata.update(
                    {
                        "render_scale": rendered["scale"],
                        "render_rotation": rendered["rotation"],
                    }
                )
                page["metadata"] = metadata
                return {"page": page, "usages": usages}

            if sparse_candidate is None and self._is_sparse_page(rendered["stats"]):
                sparse_candidate = rendered

        if sparse_candidate is not None:
            return {
                "page": self._empty_page(
                    page_number,
                    scale=sparse_candidate["scale"],
                    rotation=sparse_candidate["rotation"],
                ),
                "usages": usages,
            }

        raise ProcessingError(f"dots_native OCR failed for page {page_number}")

    def _process_rendered_page(self, page_number: int, rendered: dict[str, Any]) -> dict[str, Any]:
        usages: list[dict[str, Any]] = []
        image_data_url = rendered["data_url"]
        sparse_page = self._is_sparse_page(rendered["stats"])

        layout_response = self._request(
            self._build_payload(
                prompt=DOTS_LAYOUT_PROMPT,
                image_data_url=image_data_url,
                max_tokens=self._settings.ocr_dots_native_layout_max_tokens,
            )
        )
        if layout_response is not None:
            usages.append(layout_response["usage"] or {})
            layout_elements = self._parse_layout_response(layout_response["content"])
            if layout_elements and not self._is_picture_only(layout_elements):
                return {"page": self._layout_page(page_number, layout_elements), "usages": usages}

        ocr_response = self._request(
            self._build_payload(
                prompt=DOTS_OCR_PROMPT,
                image_data_url=image_data_url,
                max_tokens=self._settings.ocr_dots_native_ocr_max_tokens,
            )
        )
        if ocr_response is not None:
            usages.append(ocr_response["usage"] or {})
            text = ocr_response["content"].strip()
            if text:
                return {"page": self._ocr_page(page_number, text), "usages": usages}
            if sparse_page:
                return {
                    "page": self._empty_page(
                        page_number,
                        scale=rendered["scale"],
                        rotation=rendered["rotation"],
                    ),
                    "usages": usages,
                }

        return {"page": None, "usages": usages}

    def _build_payload(self, prompt: str, image_data_url: str, max_tokens: int) -> dict[str, Any]:
        return {
            "model": self._settings.ocr_dots_native_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            "temperature": 0.0,
            "max_tokens": max_tokens,
        }

    def _request(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._settings.ocr_dots_native_api_key:
            headers["Authorization"] = f"Bearer {self._settings.ocr_dots_native_api_key}"

        for attempt in range(1, max(1, self._settings.ocr_dots_native_request_retries) + 1):
            try:
                with httpx.Client(
                    base_url=self._settings.ocr_dots_native_endpoint.rstrip("/"),
                    headers=headers,
                    timeout=httpx.Timeout(self._settings.ocr_dots_native_timeout),
                ) as client:
                    response = client.post("/chat/completions", json=payload)
                    response.raise_for_status()
                    data = response.json()
                break
            except httpx.HTTPError:
                logger.warning(
                    "dots_native_request_failed attempt=%s/%s",
                    attempt,
                    self._settings.ocr_dots_native_request_retries,
                    exc_info=True,
                )
                data = None
        else:
            return None

        try:
            if data is None:
                return None
            choice = data["choices"][0]
            return {"content": choice["message"]["content"], "usage": data.get("usage")}
        except (KeyError, IndexError, TypeError):
            logger.exception("dots_native_response_invalid")
            return None

    def _page_render_candidates(self) -> list[dict[str, Any]]:
        candidates = [
            {"scale": self._settings.ocr_dots_native_render_scale, "rotation": 0},
            {"scale": self._settings.ocr_dots_native_render_scale, "rotation": 180},
            {"scale": self._settings.ocr_dots_native_render_scale, "rotation": 90},
            {"scale": self._settings.ocr_dots_native_render_scale, "rotation": 270},
        ]
        fallback_scale = self._settings.ocr_dots_native_fallback_render_scale
        if fallback_scale != self._settings.ocr_dots_native_render_scale:
            candidates.extend(
                [
                    {"scale": fallback_scale, "rotation": 0},
                    {"scale": fallback_scale, "rotation": 180},
                    {"scale": fallback_scale, "rotation": 90},
                    {"scale": fallback_scale, "rotation": 270},
                ]
            )

        deduped: list[dict[str, Any]] = []
        seen: set[tuple[float, int]] = set()
        for candidate in candidates:
            key = (candidate["scale"], candidate["rotation"])
            if key in seen:
                continue
            deduped.append(candidate)
            seen.add(key)
        return deduped

    def _render_page_candidate(
        self,
        source: Path,
        page_number: int,
        *,
        scale: float,
        rotation: int,
    ) -> dict[str, Any]:
        import fitz

        document = fitz.open(source)
        try:
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(
                    scale,
                    scale,
                ).prerotate(rotation),
                alpha=False,
            )
            png_bytes = pixmap.tobytes("png")
            stats = self._image_stats(pixmap)
        finally:
            document.close()
        return {
            "data_url": f"data:image/png;base64,{base64.b64encode(png_bytes).decode('ascii')}",
            "scale": scale,
            "rotation": rotation,
            "stats": stats,
        }

    def _parse_layout_response(self, content: str) -> list[dict[str, Any]] | None:
        cleaned = content.strip()
        if not cleaned:
            return None
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        start = min((idx for idx in (cleaned.find("["), cleaned.find("{")) if idx >= 0), default=-1)
        end_brace = cleaned.rfind("}")
        end_bracket = cleaned.rfind("]")
        end = max(end_brace, end_bracket)
        if start < 0 or end <= start:
            return None
        candidate = cleaned[start : end + 1]
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            return None

        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            if isinstance(parsed.get("layout_elements"), list):
                return [item for item in parsed["layout_elements"] if isinstance(item, dict)]
            if all(key in parsed for key in ("bbox", "category")):
                return [parsed]
        return None

    def _layout_page(self, page_number: int, layout_elements: list[dict[str, Any]]) -> dict[str, Any]:
        blocks: list[dict[str, Any]] = []
        tables: list[dict[str, Any]] = []
        figures: list[dict[str, Any]] = []
        text_chunks: list[str] = []
        markdown_chunks: list[str] = []

        for index, element in enumerate(layout_elements, start=1):
            category = str(element.get("category", "Text"))
            text = str(element.get("text") or element.get("content") or "").strip()
            bbox = self._bbox_dict(element.get("bbox"))
            normalized = self._normalize_category(category)

            if normalized == "table":
                table_id = f"page-{page_number}-table-{len(tables) + 1}"
                tables.append(
                    {
                        "id": table_id,
                        "page_number": page_number,
                        "caption": None,
                        "bbox": bbox,
                        "cells": [{"html": text}] if text else [],
                    }
                )
                if text:
                    markdown_chunks.append(text)
                    text_chunks.append(self._strip_markup(text))
                continue

            if normalized == "figure":
                figures.append(
                    {
                        "id": f"page-{page_number}-figure-{len(figures) + 1}",
                        "page_number": page_number,
                        "caption": None,
                        "bbox": bbox,
                    }
                )
                continue

            block_text = text
            if block_text:
                text_chunks.append(self._strip_markup(block_text))
                markdown_chunks.append(block_text)

            blocks.append(
                {
                    "id": f"page-{page_number}-block-{len(blocks) + 1}",
                    "type": normalized,
                    "reading_order": len(blocks) + 1,
                    "text": block_text or None,
                    "bbox": bbox,
                    "metadata": {"source_category": category},
                }
            )

        return {
            "page_number": page_number,
            "page_no": page_number,
            "text": "\n".join(chunk for chunk in text_chunks if chunk).strip(),
            "markdown": "\n\n".join(chunk for chunk in markdown_chunks if chunk).strip(),
            "blocks": blocks,
            "tables": tables,
            "figures": figures,
            "metadata": {"mode": "layout"},
        }

    def _ocr_page(self, page_number: int, content: str) -> dict[str, Any]:
        text = content.strip()
        markdown = text
        return {
            "page_number": page_number,
            "page_no": page_number,
            "text": text,
            "markdown": markdown,
            "blocks": [
                {
                    "id": f"page-{page_number}-block-1",
                    "type": "paragraph",
                    "reading_order": 1,
                    "text": text or None,
                    "bbox": None,
                    "metadata": {"source_category": "ocr_fallback"},
                }
            ],
            "tables": [],
            "figures": [],
            "metadata": {"mode": "ocr"},
        }

    def _empty_page(self, page_number: int, *, scale: float, rotation: int) -> dict[str, Any]:
        return {
            "page_number": page_number,
            "page_no": page_number,
            "text": "",
            "markdown": "",
            "blocks": [],
            "tables": [],
            "figures": [],
            "metadata": {
                "mode": "empty",
                "reason": "sparse_image",
                "render_scale": scale,
                "render_rotation": rotation,
            },
        }

    def _bbox_dict(self, bbox: Any) -> dict[str, Any] | None:
        if not isinstance(bbox, list) or len(bbox) != 4:
            return None
        return {"x0": bbox[0], "y0": bbox[1], "x1": bbox[2], "y1": bbox[3]}

    def _normalize_category(self, category: str) -> str:
        normalized = category.strip().lower().replace("-", "_")
        mapping = {
            "title": "heading",
            "section_header": "heading",
            "caption": "caption",
            "list_item": "list_item",
            "table": "table",
            "picture": "figure",
            "formula": "paragraph",
            "page_header": "paragraph",
            "page_footer": "paragraph",
            "text": "paragraph",
            "footnote": "paragraph",
        }
        return mapping.get(normalized, "paragraph")

    def _strip_markup(self, text: str) -> str:
        cleaned = text.replace("### ", "").replace("## ", "").replace("# ", "")
        return cleaned.strip()

    def _is_picture_only(self, elements: list[dict[str, Any]]) -> bool:
        if len(elements) != 1:
            return False
        return str(elements[0].get("category", "")).strip().lower() == "picture"

    def _image_stats(self, pixmap: Any) -> dict[str, float]:
        pixel_stride = max(1, int(getattr(pixmap, "n", 3)))
        samples = pixmap.samples
        pixel_count = max(1, len(samples) // pixel_stride)
        step = max(1, pixel_count // 20_000)

        total_luma = 0.0
        dark_220 = 0
        inspected = 0
        for pixel_index in range(0, pixel_count, step):
            offset = pixel_index * pixel_stride
            red = samples[offset]
            green = samples[offset + 1] if pixel_stride > 1 else red
            blue = samples[offset + 2] if pixel_stride > 2 else red
            luma = (red + green + blue) / 3.0
            total_luma += luma
            dark_220 += int(luma < 220.0)
            inspected += 1

        return {
            "mean_luma": total_luma / max(1, inspected),
            "dark_220_ratio": dark_220 / max(1, inspected),
        }

    def _is_sparse_page(self, stats: dict[str, float]) -> bool:
        return (
            float(stats.get("mean_luma", 0.0)) >= self._SPARSE_PAGE_MEAN_THRESHOLD
            and float(stats.get("dark_220_ratio", 1.0)) <= self._SPARSE_PAGE_DARK220_THRESHOLD
        )
