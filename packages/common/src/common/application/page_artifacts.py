from __future__ import annotations

import re
from typing import Any

from common.domain.models import PageArtifactModel


def build_page_artifacts(
    *,
    structured_json: dict[str, Any] | None,
    markdown_text: str,
    full_text: str,
    page_count: int,
    engine_name: str | None = None,
    engine_version: str | None = None,
    confidence_summary: dict[str, Any] | None = None,
) -> list[PageArtifactModel]:
    structured = structured_json if isinstance(structured_json, dict) else {}
    existing = structured.get("page_artifacts")
    if isinstance(existing, list) and existing:
        artifacts: list[PageArtifactModel] = []
        for item in existing:
            if isinstance(item, dict):
                artifacts.append(PageArtifactModel.model_validate(item))
        if artifacts:
            return sorted(artifacts, key=lambda page: page.page_number)

    pages = structured.get("pages")
    if isinstance(pages, list) and pages:
        by_page: dict[int, PageArtifactModel] = {}
        for index, page in enumerate(pages, start=1):
            if not isinstance(page, dict):
                continue
            artifact = _artifact_from_page(
                page,
                fallback_page_number=index,
                structured=structured,
                engine_name=engine_name,
                engine_version=engine_version,
                confidence_summary=confidence_summary,
            )
            by_page[artifact.page_number] = artifact
        if by_page:
            return _fill_missing_pages(
                by_page,
                markdown_text=markdown_text,
                full_text=full_text,
                page_count=page_count,
                structured=structured,
                engine_name=engine_name,
                engine_version=engine_version,
                confidence_summary=confidence_summary,
            )

    return _fallback_artifacts(
        markdown_text=markdown_text,
        full_text=full_text,
        page_count=page_count,
        structured=structured,
        engine_name=engine_name,
        engine_version=engine_version,
        confidence_summary=confidence_summary,
    )


def add_page_artifacts_to_structured_json(
    *,
    structured_json: dict[str, Any] | None,
    markdown_text: str,
    full_text: str,
    page_count: int,
    engine_name: str | None = None,
    engine_version: str | None = None,
    confidence_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    structured = dict(structured_json or {})
    artifacts = build_page_artifacts(
        structured_json=structured,
        markdown_text=markdown_text,
        full_text=full_text,
        page_count=page_count,
        engine_name=engine_name,
        engine_version=engine_version,
        confidence_summary=confidence_summary,
    )
    structured["page_artifacts"] = [artifact.model_dump(mode="json") for artifact in artifacts]
    return structured


def get_page_artifact_text(
    *,
    structured_json: dict[str, Any] | None,
    markdown_text: str,
    full_text: str,
    page_count: int,
    page_number: int,
    engine_name: str | None = None,
    engine_version: str | None = None,
    confidence_summary: dict[str, Any] | None = None,
) -> str:
    for artifact in build_page_artifacts(
        structured_json=structured_json,
        markdown_text=markdown_text,
        full_text=full_text,
        page_count=page_count,
        engine_name=engine_name,
        engine_version=engine_version,
        confidence_summary=confidence_summary,
    ):
        if artifact.page_number == page_number:
            return artifact.markdown or artifact.text
    return full_text or markdown_text or ""


def _artifact_from_page(
    page: dict[str, Any],
    *,
    fallback_page_number: int,
    structured: dict[str, Any],
    engine_name: str | None,
    engine_version: str | None,
    confidence_summary: dict[str, Any] | None,
) -> PageArtifactModel:
    page_number = _page_number(page, fallback_page_number)
    metadata = page.get("metadata") if isinstance(page.get("metadata"), dict) else {}
    text = _text_from_page(page)
    markdown = _markdown_from_page(page, text)
    confidence = _confidence(metadata)
    text_origin = _text_origin(page, metadata, text=text, engine_name=engine_name, structured=structured)
    quality_flags = _quality_flags(text=text, confidence=confidence, metadata=metadata)
    rotation_applied, page_order_reversed = _orientation(
        structured, confidence_summary, page_number=page_number
    )
    if _orientation_needs_review(structured, confidence_summary, page_number):
        quality_flags.append("orientation_needs_review")
    page_class = _page_class(text_origin=text_origin, quality_flags=quality_flags)
    return PageArtifactModel(
        page_number=page_number,
        text=text,
        markdown=markdown,
        blocks=_list_value(page.get("blocks")),
        tables=_list_value(page.get("tables")),
        figures=_list_value(page.get("figures")),
        width=_float_or_none(page.get("width")),
        height=_float_or_none(page.get("height")),
        text_origin=text_origin,
        page_class=page_class,
        backend=str(structured.get("backend") or engine_name or "") or None,
        backend_version=engine_version,
        rotation_applied=rotation_applied,
        page_order_reversed=page_order_reversed,
        confidence=confidence,
        quality_flags=quality_flags,
        metadata={key: value for key, value in metadata.items() if key not in {"confidence"}},
    )


def _fill_missing_pages(
    by_page: dict[int, PageArtifactModel],
    *,
    markdown_text: str,
    full_text: str,
    page_count: int,
    structured: dict[str, Any],
    engine_name: str | None,
    engine_version: str | None,
    confidence_summary: dict[str, Any] | None,
) -> list[PageArtifactModel]:
    expected_count = max(page_count, max(by_page.keys(), default=0))
    fallback = {
        artifact.page_number: artifact
        for artifact in _fallback_artifacts(
            markdown_text=markdown_text,
            full_text=full_text,
            page_count=expected_count,
            structured=structured,
            engine_name=engine_name,
            engine_version=engine_version,
            confidence_summary=confidence_summary,
        )
    }
    artifacts: list[PageArtifactModel] = []
    for page_number in range(1, expected_count + 1):
        artifacts.append(by_page.get(page_number) or fallback[page_number])
    return artifacts


def _fallback_artifacts(
    *,
    markdown_text: str,
    full_text: str,
    page_count: int,
    structured: dict[str, Any],
    engine_name: str | None,
    engine_version: str | None,
    confidence_summary: dict[str, Any] | None,
) -> list[PageArtifactModel]:
    expected_count = max(page_count, 1)
    chunks = _split_by_page_markers(markdown_text or full_text, expected_count)
    backend = str(structured.get("backend") or engine_name or "") or None
    artifacts: list[PageArtifactModel] = []
    for index in range(1, expected_count + 1):
        rotation_applied, page_order_reversed = _orientation(
            structured, confidence_summary, page_number=index
        )
        text = chunks[index - 1] if index - 1 < len(chunks) else ""
        flags = _quality_flags(text=text, confidence=None, metadata={})
        flags.append("fallback_split")
        if _orientation_needs_review(structured, confidence_summary, index):
            flags.append("orientation_needs_review")
        artifacts.append(
            PageArtifactModel(
                page_number=index,
                text=text,
                markdown=text,
                text_origin="unknown" if text.strip() else "failed",
                page_class=_page_class(text_origin="unknown" if text.strip() else "failed", quality_flags=flags),
                backend=backend,
                backend_version=engine_version,
                rotation_applied=rotation_applied,
                page_order_reversed=page_order_reversed,
                confidence=None,
                quality_flags=flags,
            )
        )
    return artifacts


def _split_by_page_markers(text: str, page_count: int) -> list[str]:
    if not text:
        return ["" for _ in range(max(page_count, 1))]
    marker_pattern = re.compile(r"^\s*(?:---|===)\s*Page\s+\d+\s*(?:---|===)?\s*$", re.IGNORECASE | re.MULTILINE)
    matches = list(marker_pattern.finditer(text))
    if matches:
        chunks: list[str] = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            chunks.append(text[start:end].strip())
        return chunks

    lines = text.splitlines()
    lines_per_page = max(1, len(lines) // max(page_count, 1))
    chunks = []
    for index in range(max(page_count, 1)):
        start = index * lines_per_page
        end = len(lines) if index == page_count - 1 else min((index + 1) * lines_per_page, len(lines))
        chunks.append("\n".join(lines[start:end]).strip())
    return chunks


def _page_number(page: dict[str, Any], fallback: int) -> int:
    raw = page.get("page_number") or page.get("page_no") or page.get("page") or page.get("index") or fallback
    try:
        number = int(raw)
    except (TypeError, ValueError):
        return fallback
    if page.get("index") == raw and page.get("page_number") is None and number == fallback - 1:
        return fallback
    return max(number, 1)


def _text_from_page(page: dict[str, Any]) -> str:
    for key in ("text", "plain_text", "content"):
        value = page.get(key)
        if isinstance(value, str) and value.strip():
            return value
    markdown = page.get("markdown")
    if isinstance(markdown, str):
        return markdown
    return ""


def _markdown_from_page(page: dict[str, Any], text: str) -> str:
    markdown = page.get("markdown") or page.get("markdown_text")
    if isinstance(markdown, str) and markdown.strip():
        return markdown
    return text


def _text_origin(
    page: dict[str, Any],
    metadata: dict[str, Any],
    *,
    text: str,
    engine_name: str | None,
    structured: dict[str, Any],
) -> str:
    if not text.strip():
        return "failed"
    declared = metadata.get("text_origin") or metadata.get("source") or metadata.get("mode")
    value = str(declared or "").lower()
    if value in {"native", "text_layer", "text-layer", "pdf_text", "layout"}:
        return "native"
    if value in {"ocr", "vision", "llm_vision", "dots"}:
        return "ocr"
    if value == "hybrid":
        return "hybrid"
    backend = str(structured.get("backend") or engine_name or "").lower()
    if backend in {"dots_native", "llm_vision"}:
        return "ocr"
    return "unknown"


def _quality_flags(*, text: str, confidence: float | None, metadata: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if not text.strip():
        flags.append("empty_text")
    elif len(text.strip()) < 20:
        flags.append("sparse_text")
    if confidence is not None and confidence < 0.5:
        flags.append("low_confidence")
    mode = str(metadata.get("mode") or "").lower()
    if mode == "empty" and "empty_text" not in flags:
        flags.append("empty_text")
    return flags


def _page_class(*, text_origin: str, quality_flags: list[str]) -> str:
    if text_origin == "failed" or "empty_text" in quality_flags:
        return "failed"
    if "low_confidence" in quality_flags or "sparse_text" in quality_flags:
        return "low_quality"
    if text_origin == "native":
        return "native"
    if text_origin == "ocr":
        return "scan"
    if text_origin == "hybrid":
        return "hybrid"
    return "unknown"


def _orientation(
    structured: dict[str, Any],
    confidence_summary: dict[str, Any] | None,
    *,
    page_number: int | None = None,
) -> tuple[int | None, bool]:
    summary = confidence_summary if isinstance(confidence_summary, dict) else {}
    orientation = structured.get("orientation_preprocess")
    if not isinstance(orientation, dict):
        orientation = summary.get("orientation_preprocess") if isinstance(summary.get("orientation_preprocess"), dict) else {}
    page_rotations = orientation.get("page_rotations")
    rotation = None
    if page_number is not None and isinstance(page_rotations, dict):
        rotation = page_rotations.get(str(page_number), page_rotations.get(page_number))
    if rotation is None:
        rotation = orientation.get("rotation_applied")
    try:
        rotation_applied = int(rotation) if rotation is not None else None
    except (TypeError, ValueError):
        rotation_applied = None
    return rotation_applied, bool(orientation.get("page_order_reversed", False))


def _orientation_needs_review(
    structured: dict[str, Any],
    confidence_summary: dict[str, Any] | None,
    page_number: int,
) -> bool:
    summary = confidence_summary if isinstance(confidence_summary, dict) else {}
    orientation = structured.get("orientation_preprocess")
    if not isinstance(orientation, dict):
        candidate = summary.get("orientation_preprocess")
        orientation = candidate if isinstance(candidate, dict) else {}
    return page_number in set(orientation.get("review_pages") or [])


def _confidence(metadata: dict[str, Any]) -> float | None:
    value = metadata.get("confidence")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _list_value(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
