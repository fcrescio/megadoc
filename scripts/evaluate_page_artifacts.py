#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/common/src"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from common.config import get_settings  # noqa: E402
from common.db.models import Document, OCRResult  # noqa: E402


def expected_rotations(payload: dict[str, Any]) -> list[tuple[str, int, int]]:
    expected: list[tuple[str, int, int]] = []
    for document in payload.get("documents") or []:
        if not isinstance(document, dict) or not document.get("case_id"):
            continue
        case_id = str(document["case_id"])
        overrides = document.get("rotations") if isinstance(document.get("rotations"), dict) else {}
        ambiguous = {int(page) for page in document.get("ambiguous_pages") or []}
        dominant = document.get("dominant_rotation")
        for page in document.get("pages") or []:
            page_number = int(page)
            if page_number in ambiguous:
                continue
            rotation = overrides.get(str(page_number), overrides.get(page_number, dominant))
            if rotation is not None:
                expected.append((case_id, page_number, int(rotation) % 360))
    return expected


def evaluate(annotations: Path, database_url: str, *, require_all: bool = False) -> dict[str, Any]:
    annotation_payload = json.loads(annotations.read_text(encoding="utf-8"))
    orientation_gold = expected_rotations(annotation_payload)
    expected_by_case: dict[str, list[tuple[int, int]]] = {}
    for case_id, page, rotation in orientation_gold:
        expected_by_case.setdefault(case_id, []).append((page, rotation))

    report: dict[str, Any] = {
        "annotations": str(annotations),
        "documents_expected": len(expected_by_case),
        "documents_evaluated": 0,
        "documents_missing": [],
        "pages": 0,
        "page_artifacts": 0,
        "pages_with_provenance": 0,
        "failed_pages_visible": 0,
        "failed_pages": 0,
        "orientation_samples": 0,
        "orientation_correct": 0,
        "native_documents": 0,
        "native_documents_without_ocr": 0,
        "errors": [],
    }
    engine = create_engine(database_url)
    with Session(engine) as session:
        for case_id, orientation_pages in sorted(expected_by_case.items()):
            row = session.execute(
                select(Document, OCRResult)
                .join(OCRResult, OCRResult.document_id == Document.id)
                .where(Document.external_id == case_id)
                .order_by(OCRResult.created_at.desc())
                .limit(1)
            ).first()
            if row is None:
                report["documents_missing"].append(case_id)
                continue
            _, ocr = row
            report["documents_evaluated"] += 1
            report["pages"] += ocr.page_count
            structured = ocr.structured_json if isinstance(ocr.structured_json, dict) else {}
            artifacts = structured.get("page_artifacts") if isinstance(structured.get("page_artifacts"), list) else []
            artifacts_by_page = {
                int(item.get("page_number")): item
                for item in artifacts
                if isinstance(item, dict) and item.get("page_number") is not None
            }
            report["page_artifacts"] += len(artifacts_by_page)
            for page_number in range(1, ocr.page_count + 1):
                artifact = artifacts_by_page.get(page_number)
                if artifact is None:
                    report["errors"].append(f"{case_id}:page_{page_number}:artifact_missing")
                    continue
                origin = artifact.get("text_origin")
                if origin in {"native", "ocr", "hybrid", "failed"}:
                    report["pages_with_provenance"] += 1
                else:
                    report["errors"].append(f"{case_id}:page_{page_number}:provenance_unknown")
                if origin == "failed":
                    report["failed_pages"] += 1
                    flags = artifact.get("quality_flags") or []
                    if artifact.get("page_class") == "failed" and "empty_text" in flags:
                        report["failed_pages_visible"] += 1
                    else:
                        report["errors"].append(f"{case_id}:page_{page_number}:failed_not_visible")

            for page_number, expected_rotation in orientation_pages:
                report["orientation_samples"] += 1
                artifact = artifacts_by_page.get(page_number) or {}
                actual = artifact.get("rotation_applied")
                if actual is not None and int(actual) % 360 == expected_rotation:
                    report["orientation_correct"] += 1
                else:
                    report["errors"].append(
                        f"{case_id}:page_{page_number}:rotation_expected_{expected_rotation}_actual_{actual}"
                    )

            summary = ocr.confidence_summary if isinstance(ocr.confidence_summary, dict) else {}
            preflight = summary.get("preflight") if isinstance(summary.get("preflight"), dict) else {}
            if preflight.get("text_extractable") is True and "image_only_likely" not in (preflight.get("flags") or []):
                report["native_documents"] += 1
                origins = {item.get("text_origin") for item in artifacts_by_page.values()}
                if origins <= {"native", "hybrid"}:
                    report["native_documents_without_ocr"] += 1
                else:
                    report["errors"].append(f"{case_id}:native_document_used_ocr")

    pages = report["pages"]
    samples = report["orientation_samples"]
    report["artifact_coverage"] = report["page_artifacts"] / pages if pages else 0.0
    report["provenance_coverage"] = report["pages_with_provenance"] / pages if pages else 0.0
    report["orientation_accuracy"] = report["orientation_correct"] / samples if samples else None
    report["passed"] = (
        report["documents_evaluated"] > 0
        and (not require_all or report["documents_evaluated"] == report["documents_expected"])
        and report["artifact_coverage"] == 1.0
        and report["provenance_coverage"] == 1.0
        and (report["orientation_accuracy"] is None or report["orientation_accuracy"] >= 0.99)
        and report["failed_pages_visible"] == report["failed_pages"]
        and report["native_documents_without_ocr"] == report["native_documents"]
        and not report["errors"]
    )
    return report


def main() -> int:
    root = Path(os.getenv("MEGADOC_ARCHIVE_GOLD_DIR", Path.home() / ".local/share/megadoc/archive-gold"))
    parser = argparse.ArgumentParser(description="Certify canonical page artifacts against private orientation gold.")
    parser.add_argument("--annotations", default=str(root / "page_annotations.json"))
    parser.add_argument("--database-url", default=get_settings().database_url)
    parser.add_argument("--require-all", action="store_true", help="Fail when an annotated document is not loaded.")
    args = parser.parse_args()
    report = evaluate(Path(args.annotations), args.database_url, require_all=args.require_all)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
