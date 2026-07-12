#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/common/src"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, selectinload  # noqa: E402

from common.config import get_settings  # noqa: E402
from common.db.models import Document, DocumentUnit, ScanUnit  # noqa: E402


def _normalized_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], pattern).date().isoformat()
        except ValueError:
            pass
    return text


def _normalized_amount(value: Any) -> Decimal | None:
    text = str(value or "").strip().replace("€", "").replace(" ", "")
    if not text:
        return None
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _latest_specialist(unit: DocumentUnit, specialist_type: str):
    results = [result for result in unit.specialist_results if result.specialist_type == specialist_type]
    return max(results, key=lambda item: item.created_at) if results else None


def evaluate_document(session: Session, case_id: str, expected: dict[str, Any]) -> dict[str, Any]:
    document = session.execute(
        select(Document).where(Document.external_id == case_id).order_by(Document.created_at.desc()).limit(1)
    ).scalar_one_or_none()
    if document is None:
        return {"case_id": case_id, "status": "not_uploaded", "errors": []}
    scan = session.execute(
        select(ScanUnit)
        .where(ScanUnit.source_document_id == document.id)
        .options(
            selectinload(ScanUnit.document_units).selectinload(DocumentUnit.document_type),
            selectinload(ScanUnit.document_units).selectinload(DocumentUnit.specialist_results),
            selectinload(ScanUnit.document_units).selectinload(DocumentUnit.specialist_jobs),
        )
        .order_by(ScanUnit.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if scan is None:
        return {"case_id": case_id, "document_id": str(document.id), "status": "ocr_pending", "errors": []}
    actual_units = sorted(scan.document_units, key=lambda unit: unit.ordinal)
    expected_units = expected.get("document_units") or []
    errors: list[str] = []
    unit_results: list[dict[str, Any]] = []
    if len(actual_units) != len(expected_units):
        errors.append(f"unit_count expected={len(expected_units)} actual={len(actual_units)}")
    actual_by_range = {(unit.start_page, unit.end_page): unit for unit in actual_units}
    for index, expected_unit in enumerate(expected_units):
        actual = actual_units[index] if index < len(actual_units) else None
        result: dict[str, Any] = {
            "index": index + 1,
            "expected_range": [expected_unit.get("start_page"), expected_unit.get("end_page")],
            "expected_type": expected_unit.get("document_type"),
        }
        if actual is None:
            result["status"] = "missing"
            unit_results.append(result)
            continue
        actual_range = [actual.start_page, actual.end_page]
        actual_type = actual.document_type.code if actual.document_type else None
        result.update({
            "actual_id": str(actual.id),
            "actual_range": actual_range,
            "actual_type": actual_type,
            "boundary_match": actual_range == result["expected_range"],
            "type_match": actual_type == result["expected_type"],
        })
        if not result["boundary_match"]:
            errors.append(f"unit_{index + 1}_boundary")
        if not result["type_match"]:
            errors.append(f"unit_{index + 1}_type")
        specialist = expected_unit.get("specialist") or {"kind": "none"}
        kind = specialist.get("kind", "none")
        specialist_type = {"payable": "utility_bill", "accounting": "accounting_statement"}.get(kind)
        if specialist_type:
            specialist_unit = actual_by_range.get(
                (expected_unit.get("start_page"), expected_unit.get("end_page"))
            )
            result["specialist_expected"] = specialist_type
            if specialist_unit is None:
                result["specialist_status"] = "not_comparable_without_exact_boundary"
                errors.append(f"unit_{index + 1}_specialist_boundary_missing")
                unit_results.append(result)
                continue
            specialist_result = _latest_specialist(specialist_unit, specialist_type)
            result["specialist_present"] = specialist_result is not None
            if specialist_result is None:
                errors.append(f"unit_{index + 1}_specialist_missing")
            elif kind == "payable":
                payload = specialist_result.result_json or {}
                comparisons = {
                    "issuer": str(payload.get("issuer") or "").strip().casefold() == str(specialist.get("issuer") or "").strip().casefold(),
                    "amount": _normalized_amount(payload.get("total_amount")) == _normalized_amount(specialist.get("amount")),
                    "due_date": _normalized_date(payload.get("due_date")) == _normalized_date(specialist.get("due_date")),
                    "payment_reference": (
                        not str(specialist.get("payment_reference") or "").strip()
                        or str(payload.get("payment_reference") or payload.get("document_number") or "").strip().casefold()
                        == str(specialist.get("payment_reference") or "").strip().casefold()
                    ),
                }
                result["payable_fields"] = comparisons
                errors.extend(f"unit_{index + 1}_payable_{field}" for field, matches in comparisons.items() if not matches)
            else:
                payload = specialist_result.result_json or {}
                result["accounting_table_pages"] = sorted({
                    table.get("page_number")
                    for table in payload.get("tables") or []
                    if isinstance(table, dict) and isinstance(table.get("page_number"), int)
                })
        unit_results.append(result)
    return {
        "case_id": case_id,
        "document_id": str(document.id),
        "scan_unit_id": str(scan.id),
        "scan_status": scan.status,
        "status": "evaluated",
        "expected_units": len(expected_units),
        "actual_units": len(actual_units),
        "units": unit_results,
        "errors": errors,
        "passed": not errors,
    }


def evaluate(annotations: Path, database_url: str) -> dict[str, Any]:
    payload = json.loads(annotations.read_text(encoding="utf-8"))
    reviewed = {
        case_id: annotation
        for case_id, annotation in (payload.get("documents") or {}).items()
        if isinstance(annotation, dict) and annotation.get("reviewed") is True
    }
    engine = create_engine(database_url)
    with Session(engine) as session:
        cases = [evaluate_document(session, case_id, annotation) for case_id, annotation in sorted(reviewed.items())]
    evaluated = [case for case in cases if case["status"] == "evaluated"]
    return {
        "annotations": str(annotations),
        "reviewed_cases": len(reviewed),
        "evaluated_cases": len(evaluated),
        "passed_cases": sum(case.get("passed") is True for case in evaluated),
        "pending_cases": sum(case["status"] != "evaluated" for case in cases),
        "cases": cases,
    }


def main() -> int:
    data_root = Path(os.getenv("MEGADOC_ARCHIVE_GOLD_DIR", str(Path.home() / ".local/share/megadoc/archive-gold")))
    parser = argparse.ArgumentParser(description="Compare processed archive documents with private gold annotations.")
    parser.add_argument("--annotations", default=str(data_root / "archive_human_annotations.json"))
    parser.add_argument("--database-url", default=get_settings().database_url)
    args = parser.parse_args()
    report = evaluate(Path(args.annotations), args.database_url)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["pending_cases"] == 0 and report["passed_cases"] == report["evaluated_cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
