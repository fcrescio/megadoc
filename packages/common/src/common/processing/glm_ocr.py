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
                image = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).tobytes("png")
                try:
                    response = client.post("chat/completions", json={
                        "model": self.settings.ocr_glm_model,
                        "messages": [{"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(image).decode()}},
                            {"type": "text", "text": "Text Recognition: Preserve tables as HTML and all other text as Markdown."},
                        ]}],
                        "temperature": 0,
                        "max_tokens": self.settings.ocr_glm_max_tokens,
                    })
                    response.raise_for_status()
                    payload = response.json()
                    choice = payload["choices"][0]
                    if choice.get("finish_reason") == "length":
                        raise ProcessingError(f"GLM OCR page {index} truncated at token limit")
                    content = choice["message"]["content"]
                    if not isinstance(content, str):
                        raise ValueError("OCR content is not text")
                except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
                    raise ProcessingError(f"GLM OCR failed on page {index}: {exc}") from exc
                pages.append(structured_glm_page(index, content.strip()))
                usage.append(payload.get("usage") or {})
        text = "\n\n".join(page["markdown"] for page in pages)
        return OCRResultModel(
            engine_name="glm_ocr", engine_version=self.settings.ocr_glm_model,
            pipeline_version=self.settings.pipeline_version,
            full_text=text, markdown_text=text,
            structured_json={"backend": "glm_ocr", "pages": pages}, page_count=len(pages),
            confidence_summary={"glm_ocr": {"model": self.settings.ocr_glm_model, "usage": usage}},
        )
