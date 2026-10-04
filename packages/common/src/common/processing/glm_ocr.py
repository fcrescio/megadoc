import base64
from html.parser import HTMLParser
from pathlib import Path

import httpx
from markdown_it import MarkdownIt

from common.config import Settings
from common.domain.exceptions import ProcessingError
from common.domain.models import OCRResultModel


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.tables = []
        self.parts = []
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.depth += 1
        if self.depth:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.depth:
            self.parts.append(f"</{tag}>")
        if tag == "table" and self.depth:
            self.depth -= 1
            if not self.depth:
                self.tables.append("".join(self.parts))
                self.parts = []

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def structured_glm_page(page_number: int, markdown: str) -> dict:
    parser = _TableParser()
    parser.feed(MarkdownIt("commonmark", {"html": True}).enable("table").render(markdown))
    return {
        "page_number": page_number,
        "page_no": page_number,
        "text": markdown,
        "markdown": markdown,
        "blocks": [{"id": f"page-{page_number}-block-1", "type": "paragraph",
                    "reading_order": 1, "text": markdown, "bbox": None}],
        "tables": [{"id": f"page-{page_number}-table-{index}", "page_number": page_number,
                    "cells": [{"html": html}], "bbox": None}
                   for index, html in enumerate(parser.tables, 1)],
        "figures": [],
        "metadata": {"mode": "ocr", "backend": "glm_ocr"},
    }


def structured_sdk_page(page_number: int, payload: dict) -> dict:
    regions = payload["pages"]
    if not isinstance(regions, list) or len(regions) != 1 or not isinstance(regions[0], list):
        raise ValueError("GLM parser must return exactly one page")
    page = structured_glm_page(page_number, payload["markdown"])
    page["blocks"] = []
    page["tables"] = []
    page["figures"] = []
    for index, region in enumerate(regions[0], 1):
        content = region.get("content") or ""
        bbox = region.get("bbox_2d")
        evidence = {"id": f"page-{page_number}-block-{index}",
                    "type": region["label"], "reading_order": index,
                    "text": content, "bbox": bbox,
                    "metadata": {"bbox_coordinate_system": "normalized_1000",
                                 "native_label": region.get("native_label")}}
        page["blocks"].append(evidence)
        if region["label"] == "table":
            tables = structured_glm_page(page_number, content)["tables"]
            if not tables:
                raise ValueError(f"GLM table region {index} has no recoverable table structure")
            for table in tables:
                table.update(id=f"page-{page_number}-table-{len(page['tables']) + 1}", bbox=bbox,
                             metadata=evidence["metadata"])
                page["tables"].append(table)
        elif region["label"] == "image":
            page["figures"].append(evidence)
    page["metadata"].update(payload.get("metadata") or {})
    page["metadata"]["sdk_raw_regions"] = payload.get("raw_pages") or []
    if "layout_regions" in payload:
        page["metadata"]["sdk_layout_regions"] = payload["layout_regions"]
    if "coverage" in payload:
        page["metadata"]["sdk_coverage"] = payload["coverage"]
    if "layout_s" in payload:
        page["metadata"]["layout_s"] = payload["layout_s"]
    return page


class GLMOCRService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def process(self, source: Path, preflight=None) -> OCRResultModel:
        import fitz

        pages = []
        usage = []
        with fitz.open(source) as document, httpx.Client(
            base_url=self.settings.ocr_glm_endpoint.rstrip("/"),
            timeout=self.settings.ocr_glm_timeout,
        ) as client:
            for index, page in enumerate(document, 1):
                image = page.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), alpha=False).tobytes("png")
                try:
                    response = client.post("parse", json={
                        "model": self.settings.ocr_glm_model,
                        "document": "data:image/png;base64," + base64.b64encode(image).decode(),
                        "max_tokens": self.settings.ocr_glm_max_tokens,
                    })
                    response.raise_for_status()
                    payload = response.json()
                    structured = structured_sdk_page(index, payload)
                except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
                    detail = str(exc)
                    if isinstance(exc, httpx.HTTPStatusError):
                        try:
                            error = exc.response.json().get("error", {})
                            if isinstance(error, dict) and isinstance(error.get("message"), str):
                                detail = error["message"]
                        except (ValueError, AttributeError):
                            pass
                    raise ProcessingError(f"GLM OCR failed on page {index}: {detail}") from exc
                pages.append(structured)
                usage.append(payload.get("usage") or {})
        text = "\n\n".join(page["markdown"] for page in pages)
        return OCRResultModel(
            engine_name="glm_ocr", engine_version=self.settings.ocr_glm_model,
            pipeline_version=self.settings.pipeline_version,
            full_text=text, markdown_text=text,
            structured_json={"backend": "glm_ocr", "pages": pages}, page_count=len(pages),
            confidence_summary={"glm_ocr": {"model": self.settings.ocr_glm_model, "usage": usage}},
        )
