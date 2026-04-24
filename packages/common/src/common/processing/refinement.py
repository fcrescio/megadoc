import base64
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, Field

from common.config import Settings
from common.domain.models import OCRResultModel
from common.processing.preflight import PDFPreflightReport

logger = logging.getLogger(__name__)


class OCRRefinementPageResult(BaseModel):
    page_number: int
    refined_text: str
    confidence: float | None = None
    notes: list[str] = Field(default_factory=list)


@dataclass
class PageCandidate:
    page_number: int
    raw_text: str
    score: float
    reasons: list[str]


class OCRRefinementService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def refine(
        self,
        source: Path,
        ocr_result: OCRResultModel,
        preflight: PDFPreflightReport | None = None,
    ) -> dict[str, Any] | None:
        if not self._settings.ocr_refinement_enabled:
            return None

        candidates = self._select_candidates(ocr_result, preflight)
        if not candidates:
            return None

        try:
            import fitz
        except ImportError:
            logger.warning("ocr_refinement_disabled_missing_renderer")
            return None

        payload_pages: list[dict[str, Any]] = []
        refined_pages: dict[int, str] = {}
        for candidate in candidates:
            image_data_url = self._render_page_data_url(fitz, source, candidate.page_number)
            if image_data_url is None:
                continue
            page_result = self._refine_page(candidate, image_data_url)
            if page_result is None:
                continue
            payload_pages.append(
                {
                    "page_number": candidate.page_number,
                    "score": round(candidate.score, 3),
                    "reasons": candidate.reasons,
                    "raw_text": candidate.raw_text,
                    "refined_text": page_result.refined_text,
                    "confidence": page_result.confidence,
                    "notes": page_result.notes,
                }
            )
            refined_pages[candidate.page_number] = page_result.refined_text

        if not payload_pages:
            return None

        page_texts = self._extract_page_texts(ocr_result)
        final_pages = []
        for page_number, raw_text in page_texts.items():
            final_pages.append(
                {
                    "page_number": page_number,
                    "text": refined_pages.get(page_number, raw_text),
                    "refined": page_number in refined_pages,
                }
            )

        return {
            "enabled": True,
            "model": self._settings.ocr_refinement_model,
            "selected_pages": [candidate.page_number for candidate in candidates],
            "page_results": payload_pages,
            "refined_page_count": len(payload_pages),
            "refined_full_text": self._join_pages(final_pages),
            "summary": {
                "promoted_to_primary_text": self._settings.ocr_refinement_promote_text,
                "selected_pages": [candidate.page_number for candidate in candidates],
                "refined_page_count": len(payload_pages),
            },
        }

    def _select_candidates(
        self,
        ocr_result: OCRResultModel,
        preflight: PDFPreflightReport | None,
    ) -> list[PageCandidate]:
        page_texts = self._extract_page_texts(ocr_result)
        preflight_flags = set((preflight.flags if preflight else []) or [])
        candidates: list[PageCandidate] = []

        for page_number, raw_text in page_texts.items():
            score = 0.0
            reasons: list[str] = []
            stripped = raw_text.strip()

            if not stripped:
                continue

            if "image_only_likely" in preflight_flags:
                score += 0.15
                reasons.append("image_only_likely")
            if "heavy_scan" in preflight_flags:
                score += 0.15
                reasons.append("heavy_scan")

            compact_tokens = re.findall(r"\b\S{18,}\b", stripped)
            if compact_tokens:
                score += min(0.35, 0.04 * len(compact_tokens))
                reasons.append(f"compact_tokens:{len(compact_tokens)}")

            alnum_runs = re.findall(r"[A-Za-z0-9]{14,}", stripped)
            if alnum_runs:
                score += min(0.2, 0.02 * len(alnum_runs))
                reasons.append(f"long_alnum_runs:{len(alnum_runs)}")

            nonempty_lines = [line.strip() for line in stripped.splitlines() if line.strip()]
            if nonempty_lines:
                average_spaces = sum(line.count(" ") for line in nonempty_lines) / len(nonempty_lines)
                if average_spaces < 2 and len(stripped) > 250:
                    score += 0.15
                    reasons.append("sparse_spacing")

            words = re.findall(r"\S+", stripped)
            if words:
                average_word_length = sum(len(word) for word in words) / len(words)
                if average_word_length > 10:
                    score += 0.15
                    reasons.append("long_average_word_length")

            punctuation_runs = re.findall(r"[,:;./-]{3,}", stripped)
            if punctuation_runs:
                score += min(0.1, 0.02 * len(punctuation_runs))
                reasons.append(f"punctuation_runs:{len(punctuation_runs)}")

            if score >= self._settings.ocr_refinement_min_page_score:
                candidates.append(
                    PageCandidate(
                        page_number=page_number,
                        raw_text=stripped[:4000],
                        score=score,
                        reasons=reasons,
                    )
                )

        candidates.sort(key=lambda item: (-item.score, item.page_number))
        return candidates[: self._settings.ocr_refinement_max_pages]

    def _extract_page_texts(self, ocr_result: OCRResultModel) -> dict[int, str]:
        structured = ocr_result.structured_json or {}
        pages = structured.get("pages") or []
        page_texts: dict[int, str] = {}

        if isinstance(pages, list):
            for index, page in enumerate(pages, start=1):
                if not isinstance(page, dict):
                    continue
                page_number = int(page.get("page_no") or page.get("page_number") or index)
                blocks = page.get("blocks") or []
                ordered_blocks = sorted(blocks, key=lambda block: block.get("reading_order", 0))
                lines = []
                for block in ordered_blocks:
                    text = (block.get("text") or "").strip()
                    if text:
                        lines.append(text)
                if lines:
                    page_texts[page_number] = "\n".join(lines)
        elif isinstance(pages, dict):
            for page_key, page in pages.items():
                if not isinstance(page, dict):
                    continue
                page_number = int(page.get("page_no") or page.get("page_number") or page_key)
                page_texts.setdefault(page_number, "")

        page_texts = {page_number: text for page_number, text in page_texts.items() if text.strip()}

        if not page_texts:
            texts = structured.get("texts") or []
            if isinstance(texts, list):
                collected: dict[int, list[str]] = {}
                for entry in texts:
                    if not isinstance(entry, dict):
                        continue
                    text = (entry.get("text") or entry.get("orig") or "").strip()
                    if not text:
                        continue
                    provenance = entry.get("prov") or []
                    if isinstance(provenance, list) and provenance:
                        page_number = int((provenance[0] or {}).get("page_no") or 1)
                    else:
                        page_number = 1
                    collected.setdefault(page_number, []).append(text)
                for page_number, lines in collected.items():
                    page_texts[page_number] = "\n".join(lines)

        if page_texts:
            return page_texts

        fallback_text = (ocr_result.full_text or "").strip()
        if not fallback_text:
            return {}
        return {1: fallback_text[:7000]}

    def _render_page_data_url(self, fitz_module, source: Path, page_number: int) -> str | None:
        document = fitz_module.open(source)
        try:
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=fitz_module.Matrix(1.5, 1.5), alpha=False)
            png_bytes = pixmap.tobytes("png")
        finally:
            document.close()

        encoded = base64.b64encode(png_bytes).decode("ascii")
        return f"data:image/png;base64,{encoded}"

    def _refine_page(self, candidate: PageCandidate, image_data_url: str) -> OCRRefinementPageResult | None:
        messages = [
            {
                "role": "system",
                "content": (
                    "You refine OCR conservatively. Repair spacing, line breaks, and obvious OCR glue. "
                    "Do not invent text not visible on the page. If uncertain, keep the OCR token as-is."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Page number: {candidate.page_number}\n"
                            f"Raw OCR text:\n{candidate.raw_text}\n\n"
                            "Return only JSON with fields: page_number, refined_text, confidence, notes. "
                            "Keep names, numbers, dates, and amounts faithful to the page image. "
                            "Keep notes short."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            },
        ]
        schema = OCRRefinementPageResult.model_json_schema()

        result = self._request_page_refinement(messages, schema, candidate.page_number, use_response_format=True)
        if result is not None:
            return result

        fallback_messages = [
            *messages,
            {
                "role": "user",
                "content": (
                    "Return only valid JSON. Keep notes to at most two short items. "
                    "Do not include markdown fences or commentary."
                ),
            },
        ]
        return self._request_page_refinement(
            fallback_messages,
            schema,
            candidate.page_number,
            use_response_format=False,
        )

    def _request_page_refinement(
        self,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        page_number: int,
        use_response_format: bool,
    ) -> OCRRefinementPageResult | None:
        payload: dict[str, Any] = {
            "model": self._settings.ocr_refinement_model,
            "messages": messages,
            "temperature": 0.0,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if use_response_format:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "OCRRefinementPageResult",
                    "schema": schema,
                },
            }

        if self._settings.ocr_refinement_max_tokens:
            payload["max_tokens"] = self._settings.ocr_refinement_max_tokens

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self._settings.ocr_refinement_api_key:
            headers["Authorization"] = f"Bearer {self._settings.ocr_refinement_api_key}"

        try:
            with httpx.Client(
                base_url=self._settings.ocr_refinement_endpoint.rstrip("/"),
                headers=headers,
                timeout=httpx.Timeout(self._settings.ocr_refinement_timeout),
            ) as client:
                response = client.post("/chat/completions", json=payload)
                response.raise_for_status()
        except httpx.HTTPError:
            logger.exception("ocr_refinement_request_failed", extra={"page_number": page_number})
            return None

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            parsed = OCRRefinementPageResult.model_validate_json(self._extract_json_text(content))
            if parsed.page_number != page_number:
                parsed.page_number = page_number
            return parsed
        except Exception:
            logger.exception("ocr_refinement_response_invalid", extra={"page_number": page_number})
            return None

    def _join_pages(self, pages: list[dict[str, Any]]) -> str:
        chunks = []
        for page in sorted(pages, key=lambda item: item["page_number"]):
            text = (page["text"] or "").strip()
            if not text:
                continue
            chunks.append(f"--- Page {page['page_number']} ---\n{text}")
        return "\n\n".join(chunks)

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

        match = re.search(r"(\{.*\})", cleaned, re.DOTALL)
        if match:
            return match.group(1).strip()
        raise ValueError("No JSON object found in OCR refinement response")
