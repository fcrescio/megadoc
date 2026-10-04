#!/usr/bin/env python3
"""Read-only OCR comparison. All source material stays in an external directory."""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/common/src"))

import fitz
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from common.config import get_settings
from common.db.models import DocumentVersion, OCRResult
from common.processing.glm_ocr import GLMOCRService, structured_glm_page
from common.processing.llm_vision import LLMVisionOCRService
from common.storage.backends import get_storage_backend


def save(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    temporary.replace(path)


def visible_text(value):
    return BeautifulSoup(value, "html.parser").get_text(" ", strip=True)


def comparison(reference, candidate):
    old = visible_text(reference)
    new = visible_text(candidate)
    tokens = lambda value: re.findall(r"\w+", value.casefold())
    # Concordance only: the archived OCR is NOT a gold transcript.
    number_pattern = r"(?<!\w)\d+(?:[.,/]\d+)*(?!\w)"
    left = Counter(re.findall(number_pattern, old))
    right = Counter(re.findall(number_pattern, new))
    return {
        "word_sequence_agreement_not_accuracy": round(SequenceMatcher(None, tokens(old), tokens(new), autojunk=False).ratio(), 4),
        "baseline_numeric_occurrences": sum(left.values()),
        "shared_numeric_occurrences": sum((left & right).values()),
        "baseline_numbers_absent": list((left - right).elements()),
        "candidate_numbers_added": list((right - left).elements()),
    }


def normalized_pdf(source, target, baseline, rotations_override=None):
    orientation = (baseline.get("confidence_summary") or {}).get("orientation_preprocess") or {}
    applied = orientation.get("applied") is True
    reverse = applied and orientation.get("page_order_reversed", False)
    rotation = int(orientation.get("rotation_applied") or 0) if applied else 0
    per_page = orientation.get("page_rotations") or {}
    archived_pages = baseline["structured_json"].get("pages") or []
    with fitz.open(source) as original, fitz.open() as output:
        if rotations_override is not None and len(rotations_override) != len(original):
            raise ValueError("Provide one rotation for every source page")
        order = list(range(len(original)))
        if reverse:
            order.reverse()
        mapping = []
        for index, original_index in enumerate(order):
            output.insert_pdf(original, from_page=original_index, to_page=original_index)
            angle = int(per_page.get(str(original_index + 1), rotation))
            render_rotation = int((archived_pages[index].get("metadata") or {}).get("render_rotation", 0)) if index < len(archived_pages) else 0
            if rotations_override is not None:
                angle = rotations_override[original_index]
                render_rotation = 0
            output[index].set_rotation((output[index].rotation + angle + render_rotation) % 360)
            mapping.append({"page": index + 1, "original_page": original_index + 1, "rotation": angle, "dots_render_rotation": render_rotation})
        output.save(target)
    return mapping


def snapshot(document_id, directory, settings):
    path = directory / "dots.json"
    if path.exists():
        baseline = json.loads(path.read_text())
        if hashlib.sha256((directory / "original.pdf").read_bytes()).hexdigest() != baseline["source_sha256"]:
            raise ValueError("Saved source checksum mismatch")
        return baseline
    engine = create_engine(settings.database_url)
    with Session(engine) as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        result = session.scalars(select(OCRResult).where(OCRResult.document_id == uuid.UUID(document_id), OCRResult.engine_name == "dots_native").order_by(OCRResult.created_at.desc()).limit(1)).one()
        version = session.get(DocumentVersion, result.document_version_id)
        original = get_storage_backend(settings).read_bytes(version.storage_bucket, version.storage_object_key)
        baseline = {column.name: getattr(result, column.name) for column in OCRResult.__table__.columns}
    engine.dispose()
    baseline["source_sha256"] = hashlib.sha256(original).hexdigest()
    (directory / "original.pdf").write_bytes(original)
    save(path, baseline)
    return baseline


def run_backend(backend, source, directory, settings, baseline):
    path = directory / f"{backend}.json"
    if path.exists():
        return json.loads(path.read_text())
    service = GLMOCRService(settings) if backend == "glm" else LLMVisionOCRService(settings)
    requests = []
    original_send = httpx.Client.send

    def recorded_send(client, request, *args, **kwargs):
        start = time.monotonic()
        response = original_send(client, request, *args, **kwargs)
        response.read()
        requests.append({"seconds": round(time.monotonic() - start, 3), "status_code": response.status_code, "body": response.json()})
        save(directory / f"{backend}-requests.json", requests)
        print(json.dumps({"backend": backend, "page_request": len(requests), "seconds": requests[-1]["seconds"]}), flush=True)
        return response

    start = time.monotonic()
    report = {"backend": backend, "status": "failed"}
    try:
        with patch.object(httpx.Client, "send", recorded_send):
            result = service.process(source)
        report["result"] = result.model_dump(mode="json")
        report["status"] = "ok"
        report["concordance"] = comparison(baseline["full_text"], result.full_text)
        pages = result.structured_json["pages"]
        report["tables_in_adapter"] = sum(len(page.get("tables") or []) for page in pages)
        report["tables_in_markdown"] = sum(len(structured_glm_page(i, page.get("markdown") or "")["tables"]) for i, page in enumerate(pages, 1))
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    report["seconds"] = round(time.monotonic() - start, 3)
    report["finish_reasons"] = [choice.get("finish_reason") for record in requests for choice in record["body"].get("choices", [])]
    report["truncated"] = "length" in report["finish_reasons"]
    if report["truncated"]:
        report["status"] = "truncated"
    save(path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--glm-endpoint", default="http://host.docker.internal:18030/v1")
    parser.add_argument("--qwen-endpoint", default="http://host.docker.internal:18020/v1")
    parser.add_argument("--qwen-model", default="qwen3.8-27b")
    parser.add_argument("--page-rotations", help="Supplementary experiment: comma-separated explicit source-page rotations")
    parser.add_argument("document_ids", nargs="+")
    args = parser.parse_args()
    rotations = [int(value) for value in args.page_rotations.split(",")] if args.page_rotations else None
    if rotations is not None and (len(args.document_ids) != 1 or any(value not in (0, 90, 180, 270) for value in rotations)):
        parser.error("Rotation overrides require one document and right-angle rotations")
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error("Evidence must stay outside the Git checkout")
    settings = get_settings().model_copy(update={"ocr_glm_endpoint": args.glm_endpoint, "ocr_llm_vision_endpoint": args.qwen_endpoint, "ocr_llm_vision_model": args.qwen_model, "ocr_llm_vision_timeout": 600, "ocr_llm_vision_render_scale": 1.5})
    for document_id in args.document_ids:
        uuid.UUID(document_id)
        directory = output / document_id
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        baseline = snapshot(document_id, directory, settings)
        normalized = directory / "normalized.pdf"
        if not normalized.exists():
            mapping = normalized_pdf(directory / "original.pdf", normalized, baseline, rotations)
            save(directory / "page_mapping.json", mapping)
        manifest = {"source_sha256": baseline["source_sha256"], "normalized_sha256": hashlib.sha256(normalized.read_bytes()).hexdigest(), "historical_engine": baseline["engine_version"], "historical_created_at": baseline["created_at"], "scope": "OCR only; archived orientation replayed; no downstream jobs", "glm_model": settings.ocr_glm_model, "qwen_model": settings.ocr_llm_vision_model, "glm_endpoint": args.glm_endpoint, "qwen_endpoint": args.qwen_endpoint, "render_scale": 1.5, "glm_max_tokens": settings.ocr_glm_max_tokens, "qwen_max_tokens": settings.ocr_llm_vision_max_tokens}
        manifest_path = directory / "manifest.json"
        manifest["rotation_overrides"] = rotations
        if manifest_path.exists() and json.loads(manifest_path.read_text()) != manifest:
            raise ValueError("Experiment settings changed: use a new output directory")
        save(manifest_path, manifest)
        summary = {"document_id": document_id, "historical_pages": baseline["page_count"], "historical_tables": sum(len(page.get("tables") or []) for page in baseline["structured_json"].get("pages", []))}
        for backend in ("glm", "qwen"):
            result = run_backend(backend, normalized, directory, settings, baseline)
            summary[backend] = {key: value for key, value in result.items() if key != "result"}
        save(directory / "comparison.json", summary)
        print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
