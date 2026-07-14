#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for source in (
    ROOT / "packages/common/src",
    ROOT / "services/knowledge_classifier/src",
    ROOT / "services/specialist_worker/src",
):
    sys.path.insert(0, str(source))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from common.application.specialist_contracts import SpecialistExecutionContext  # noqa: E402
from common.application.specialists import extract_document_unit_text  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.db.models import Document, DocumentType, DocumentUnit, OCRResult  # noqa: E402
from specialist_worker.registry import build_specialist_registry  # noqa: E402


def _norm(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


def _amount(value: Any) -> Decimal | None:
    text = str(value or "").strip().replace("€", "").replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        decimal_separator = "," if text.rfind(",") > text.rfind(".") else "."
        thousands_separator = "." if decimal_separator == "," else ","
        text = text.replace(thousands_separator, "").replace(decimal_separator, ".")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _date(value: Any) -> str | None:
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], pattern).date().isoformat()
        except ValueError:
            pass
    return text or None


def _text_match(actual: Any, expected: Any) -> bool:
    left, right = _norm(actual), _norm(expected)
    if not left or not right:
        return False
    left_tokens, right_tokens = set(left.split()), set(right.split())
    return left in right or right in left or left_tokens <= right_tokens or right_tokens <= left_tokens


def _normalized_page(page: int, ocr: OCRResult) -> int:
    structured = ocr.structured_json if isinstance(ocr.structured_json, dict) else {}
    orientation = structured.get("orientation_preprocess")
    if isinstance(orientation, dict) and orientation.get("page_order_reversed"):
        return int(ocr.page_count) + 1 - page
    return page


def _payable_comparisons(payload: dict[str, Any], gold: dict[str, Any]) -> dict[str, bool]:
    comparisons = {
        "payable_kind": str(payload.get("payable_kind") or "") == str(gold.get("payable_kind") or ""),
        "issuer": _text_match(payload.get("issuer"), gold.get("issuer")),
        "recipient": _text_match(payload.get("recipient") or payload.get("account_holder"), gold.get("recipient")),
        "due_date": _date(payload.get("due_date")) == _date(gold.get("due_date")),
        "amount": _amount(payload.get("total_amount")) == _amount(gold.get("amount")),
        "currency": str(payload.get("currency") or "").upper() == str(gold.get("currency") or "").upper(),
        "payment_reference": _norm(payload.get("payment_reference") or payload.get("document_number")) == _norm(gold.get("payment_reference")),
    }
    if gold.get("subject"):
        comparisons["subject"] = _text_match(payload.get("subject") or payload.get("service_type"), gold.get("subject"))
    if gold.get("issue_date"):
        comparisons["issue_date"] = _date(payload.get("issue_date")) == _date(gold.get("issue_date"))
    return comparisons


def _accounting_check(tables: list[dict[str, Any]], check: dict[str, Any]) -> dict[str, Any]:
    page = check.get("page")
    table_hint, row_hint, column_hint = (_norm(check.get(key)) for key in ("table", "row", "column"))
    expected = check.get("expected")
    candidates = []
    for table in tables:
        if page is not None and table.get("page_number") != page:
            continue
        searchable_table = _norm(" ".join(str(table.get(key) or "") for key in ("table_id", "table_type", "explanation")))
        candidates.append((table_hint and _text_match(searchable_table, table_hint), table))
    for _, table in sorted(candidates, key=lambda item: item[0], reverse=True):
        headers = [str(header) for header in table.get("headers") or []]
        matching_columns = [header for header in headers if not column_hint or _text_match(header, column_hint)]
        for row in table.get("rows") or []:
            cells = row.get("cells") if isinstance(row, dict) and isinstance(row.get("cells"), dict) else {}
            if row_hint:
                row_parts = [_norm(part) for part in re.split(r"\s*/\s*", str(check.get("row") or "")) if _norm(part)]
                if not all(any(_text_match(value, part) for value in cells.values()) for part in row_parts):
                    continue
            for column in matching_columns:
                actual = cells.get(column)
                matches = (
                    _amount(actual) == _amount(expected)
                    if check.get("comparison") == "amount"
                    else _text_match(actual, expected)
                )
                if matches:
                    return {
                        "matched": True,
                        "page": table.get("page_number"),
                        "table_id": table.get("table_id"),
                        "row_id": row.get("row_id"),
                        "column": column,
                        "actual": actual,
                    }
    return {"matched": False}


def evaluate(annotations: Path, database_url: str, *, accounting_llm: bool = False) -> dict[str, Any]:
    gold = json.loads(annotations.read_text(encoding="utf-8"))
    if accounting_llm:
        from specialist_worker.tasks import _accounting_reconciliation_provider

        provider_factory = _accounting_reconciliation_provider
    else:
        provider_factory = lambda: None
    registry = build_specialist_registry(provider_factory)
    cases: list[dict[str, Any]] = []
    field_total = field_matches = check_total = check_matches = lineage_total = lineage_matches = 0
    engine = create_engine(database_url)
    with Session(engine) as session:
        for case_id, annotation in sorted((gold.get("documents") or {}).items()):
            if not isinstance(annotation, dict) or annotation.get("reviewed") is not True:
                continue
            row = session.execute(
                select(Document, OCRResult)
                .join(OCRResult, OCRResult.document_id == Document.id)
                .where(Document.external_id == case_id)
                .order_by(OCRResult.created_at.desc())
                .limit(1)
            ).first()
            for ordinal, expected_unit in enumerate(annotation.get("document_units") or [], start=1):
                specialist = deepcopy(expected_unit.get("specialist")) if isinstance(expected_unit, dict) else None
                kind = specialist.get("kind") if isinstance(specialist, dict) else "none"
                if kind not in {"payable", "accounting"}:
                    continue
                result: dict[str, Any] = {"case_id": case_id, "unit": ordinal, "kind": kind}
                if row is None:
                    result["status"] = "document_not_loaded"
                    cases.append(result)
                    continue
                _, ocr = row
                source_start = int(expected_unit["start_page"])
                source_end = int(expected_unit["end_page"])
                normalized_range = sorted((_normalized_page(source_start, ocr), _normalized_page(source_end, ocr)))
                if kind == "accounting":
                    specialist["checks"] = [
                        {**check, "page": _normalized_page(int(check["page"]), ocr)}
                        for check in specialist.get("checks") or []
                    ]
                    source_table_pages = [
                        int(page) for page in str(specialist.get("table_pages") or "").split(",")
                        if page.strip().isdigit()
                    ]
                    specialist["table_pages"] = ",".join(
                        str(_normalized_page(page, ocr)) for page in source_table_pages
                    )
                unit = DocumentUnit(
                    id=uuid.uuid4(),
                    ordinal=ordinal,
                    start_page=normalized_range[0],
                    end_page=normalized_range[1],
                    review_status="human_reviewed",
                    segmentation_confidence=1.0,
                    document_type_confidence=1.0,
                )
                unit.document_type = DocumentType(code=str(expected_unit.get("document_type") or "altro"), name="gold")
                unit.entities = []
                capability = "utility_bill" if kind == "payable" else "accounting_statement"
                handler = registry.get(capability)
                extraction = handler.extract(SpecialistExecutionContext(
                    session=session,
                    document_unit=unit,
                    text=extract_document_unit_text(unit, ocr),
                    structured_json=ocr.structured_json or {},
                    input_version=f"gold:{ocr.id}:{unit.start_page}-{unit.end_page}",
                ))
                validation = handler.validate(extraction)
                result.update({
                    "status": "evaluated",
                    "confidence": extraction.confidence,
                    "validation": validation.status,
                    "input_text_chars": len(extract_document_unit_text(unit, ocr)),
                    "source_pdf_pages": [source_start, source_end],
                    "normalized_ocr_pages": normalized_range,
                })
                if kind == "payable":
                    comparisons = _payable_comparisons(extraction.payload, specialist)
                    result["fields"] = comparisons
                    result["actual"] = {
                        key: extraction.payload.get(key)
                        for key in (
                            "payable_kind", "issuer", "recipient", "account_holder", "service_type",
                            "issue_date", "due_date", "total_amount", "currency", "payment_reference",
                            "document_number",
                        )
                    }
                    field_total += len(comparisons)
                    field_matches += sum(comparisons.values())
                    evidence_fields = {item.field for item in extraction.evidence}
                    evidence_aliases = {"amount": "total_amount"}
                    required_evidence = {field for field, matched in comparisons.items() if matched and field not in {"payable_kind"}}
                    result["lineage"] = {
                        field: evidence_aliases.get(field, field) in evidence_fields
                        for field in sorted(required_evidence)
                    }
                    lineage_total += len(required_evidence)
                    lineage_matches += sum(result["lineage"].values())
                else:
                    tables = [table for table in extraction.payload.get("tables") or [] if isinstance(table, dict)]
                    expected_pages = {int(page) for page in str(specialist.get("table_pages") or "").split(",") if page.strip().isdigit()}
                    actual_pages = {table.get("page_number") for table in tables if isinstance(table.get("page_number"), int)}
                    result["table_pages"] = {"expected": sorted(expected_pages), "actual": sorted(actual_pages), "matched": expected_pages <= actual_pages}
                    result["tables"] = tables
                    check_results = [_accounting_check(tables, check) for check in specialist.get("checks") or []]
                    result["checks"] = check_results
                    check_total += len(check_results)
                    check_matches += sum(item["matched"] for item in check_results)
                    lineage_total += sum(item["matched"] for item in check_results)
                    lineage_matches += sum(
                        item["matched"] and all(item.get(key) is not None for key in ("page", "table_id", "row_id", "column"))
                        for item in check_results
                    )
                cases.append(result)
    evaluated = [case for case in cases if case.get("status") == "evaluated"]
    report = {
        "annotations": str(annotations),
        "accounting_llm": accounting_llm,
        "specialist_cases": len(cases),
        "evaluated_cases": len(evaluated),
        "payable_field_accuracy": field_matches / field_total if field_total else None,
        "accounting_check_accuracy": check_matches / check_total if check_total else None,
        "lineage_coverage": lineage_matches / lineage_total if lineage_total else None,
        "counts": {
            "payable_fields": field_total,
            "payable_matches": field_matches,
            "accounting_checks": check_total,
            "accounting_matches": check_matches,
            "lineage_expected": lineage_total,
            "lineage_present": lineage_matches,
        },
        "cases": cases,
    }
    report["passed"] = bool(evaluated) and all(
        value is None or value >= target
        for value, target in (
            (report["payable_field_accuracy"], 0.95),
            (report["accounting_check_accuracy"], 0.98),
            (report["lineage_coverage"], 1.0),
        )
    ) and len(evaluated) == len(cases)
    return report


def main() -> int:
    root = Path(os.getenv("MEGADOC_ARCHIVE_GOLD_DIR", Path.home() / ".local/share/megadoc/archive-gold"))
    parser = argparse.ArgumentParser(description="Evaluate specialist handlers directly on gold page ranges.")
    parser.add_argument("--annotations", default=str(root / "archive_human_annotations.json"))
    parser.add_argument("--database-url", default=get_settings().database_url)
    parser.add_argument("--accounting-llm", action="store_true", help="Use the same accounting LLM provider as the worker.")
    args = parser.parse_args()
    report = evaluate(Path(args.annotations), args.database_url, accounting_llm=args.accounting_llm)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
