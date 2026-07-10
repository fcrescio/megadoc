#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for source_path in (
    ROOT / "packages" / "common" / "src",
    ROOT / "services" / "knowledge_classifier" / "src",
    ROOT / "services" / "specialist_worker" / "src",
):
    sys.path.insert(0, str(source_path))

from common.db.models import DocumentUnit  # noqa: E402
from knowledge_classifier.llm.mock import MockDeterministicProvider  # noqa: E402
from knowledge_classifier.services.classification import ClassificationService  # noqa: E402
from knowledge_classifier.services.routing import PipelineRouterService  # noqa: E402
from specialist_worker.services.accounting_statement import process_accounting_statement  # noqa: E402


class _NoDBSession:
    pass


def _document_unit() -> DocumentUnit:
    return DocumentUnit(start_page=1, end_page=1, ordinal=1, review_status="auto_accepted")


def _case_text(case: dict[str, Any]) -> str:
    return str(case.get("text") or "").replace("\\n", "\n")


def _check_equal(errors: list[str], label: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        errors.append(f"{label}: expected {expected!r}, got {actual!r}")


def _evaluate_classification(case: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    service = ClassificationService(MockDeterministicProvider(), _NoDBSession())
    result = service.classify_document(_case_text(case))
    errors: list[str] = []
    _check_equal(errors, "classification.primary_type", result.primary_type.type_code, expected.get("primary_type"))
    min_confidence = expected.get("min_confidence")
    if min_confidence is not None and result.primary_type.confidence < float(min_confidence):
        errors.append(
            f"classification.confidence: expected >= {min_confidence}, got {result.primary_type.confidence:.3f}"
        )
    max_confidence = expected.get("max_confidence")
    if max_confidence is not None and result.primary_type.confidence > float(max_confidence):
        errors.append(
            f"classification.confidence: expected <= {max_confidence}, got {result.primary_type.confidence:.3f}"
        )
    return errors


def _evaluate_routing(case: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    service = PipelineRouterService(MockDeterministicProvider())
    decision = service.route_text(_case_text(case))
    errors: list[str] = []
    _check_equal(errors, "routing.pipeline_id", decision.pipeline_id, expected.get("pipeline_id"))
    _check_equal(errors, "routing.family", decision.family, expected.get("family"))
    return errors


def _evaluate_accounting(case: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    result, confidence = process_accounting_statement(
        _document_unit(),
        _case_text(case),
        "gold:v1",
    )
    errors: list[str] = []
    _check_equal(errors, "accounting.statement_type", result.get("statement_type"), expected.get("statement_type"))
    _check_equal(
        errors,
        "accounting.account_extraction_mode",
        result.get("account_extraction_mode"),
        expected.get("account_extraction_mode"),
    )
    if len(result.get("tables") or []) < int(expected.get("min_tables", 0)):
        errors.append(
            f"accounting.tables: expected at least {expected.get('min_tables')}, got {len(result.get('tables') or [])}"
        )
    actual_roles = {
        section.get("role")
        for section in result.get("sections") or []
        if isinstance(section, dict) and section.get("role")
    }
    for role in expected.get("required_section_roles") or []:
        if role not in actual_roles:
            errors.append(f"accounting.sections: missing role {role!r}")
    if expected.get("requires_normalized_amounts"):
        if not any(
            row.get("normalized_amounts")
            for table in result.get("tables") or []
            for row in table.get("rows") or []
            if isinstance(row, dict)
        ):
            errors.append("accounting.normalized_amounts: no normalized monetary values found")
    if confidence <= 0:
        errors.append(f"accounting.confidence: expected positive confidence, got {confidence:.3f}")
    return errors


def evaluate_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    case_results: list[dict[str, Any]] = []
    for case in manifest.get("cases") or []:
        errors: list[str] = []
        expected = case.get("expect") or {}
        if "classification" in expected:
            errors.extend(_evaluate_classification(case, expected["classification"]))
        if "routing" in expected:
            errors.extend(_evaluate_routing(case, expected["routing"]))
        if "accounting" in expected:
            errors.extend(_evaluate_accounting(case, expected["accounting"]))
        case_results.append(
            {
                "id": case.get("id"),
                "passed": not errors,
                "errors": errors,
            }
        )
    passed = sum(1 for result in case_results if result["passed"])
    return {
        "manifest": str(path),
        "total": len(case_results),
        "passed": passed,
        "failed": len(case_results) - passed,
        "cases": case_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Megadoc's minimal gold corpus.")
    parser.add_argument(
        "manifest",
        nargs="?",
        default=str(ROOT / "tests" / "gold" / "manifest.json"),
        help="Path to the gold corpus manifest JSON.",
    )
    args = parser.parse_args()
    summary = evaluate_manifest(Path(args.manifest))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
