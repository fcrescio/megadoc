#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.archive_annotation_server import load_annotations, load_cases


def validate_annotations(cases: list[dict[str, object]], payload: dict[str, object]) -> dict[str, object]:
    errors: list[str] = []
    documents = payload.get("documents") if isinstance(payload.get("documents"), dict) else {}
    specialist_counts = {"payable": 0, "accounting": 0}
    unit_count = 0
    for case in cases:
        case_id = str(case["case_id"])
        page_count = int(case["pages"])
        annotation = documents.get(case_id)
        if not isinstance(annotation, dict):
            errors.append(f"{case_id}: annotation missing")
            continue
        if annotation.get("reviewed") is not True:
            errors.append(f"{case_id}: review not completed")
        if annotation.get("orientation_verified") is not True:
            errors.append(f"{case_id}: orientation not verified")
        if not str(annotation.get("document_type") or "").strip():
            errors.append(f"{case_id}: document type missing")
        if not str(annotation.get("title") or "").strip():
            errors.append(f"{case_id}: title missing")
        units = annotation.get("document_units")
        if not isinstance(units, list) or not units:
            errors.append(f"{case_id}: document units missing")
        else:
            covered: list[int] = []
            for index, unit in enumerate(units, start=1):
                if not isinstance(unit, dict):
                    errors.append(f"{case_id}: invalid unit {index}")
                    continue
                start, end = unit.get("start_page"), unit.get("end_page")
                if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > page_count:
                    errors.append(f"{case_id}: invalid page range for unit {index}")
                    continue
                if not str(unit.get("document_type") or "").strip() or not str(unit.get("title") or "").strip():
                    errors.append(f"{case_id}: type/title missing for unit {index}")
                covered.extend(range(start, end + 1))
                unit_count += 1
            if sorted(covered) != list(range(1, page_count + 1)):
                errors.append(f"{case_id}: unit ranges must cover every page exactly once")
        specialist = annotation.get("specialist")
        if isinstance(specialist, dict) and specialist.get("kind") in specialist_counts:
            kind = str(specialist["kind"])
            specialist_counts[kind] += 1
            required = (
                ("issuer", "amount", "due_date")
                if kind == "payable"
                else ("table_pages", "cell_checks")
            )
            for field in required:
                if not str(specialist.get(field) or "").strip():
                    errors.append(f"{case_id}: {kind} field {field} missing")
    questions = payload.get("questions") if isinstance(payload.get("questions"), list) else []
    if len(questions) < 30:
        errors.append(f"questions: expected at least 30, got {len(questions)}")
    case_ids = {str(case["case_id"]) for case in cases}
    for index, question in enumerate(questions, start=1):
        if not isinstance(question, dict) or not str(question.get("question") or "").strip():
            errors.append(f"question {index}: text missing")
            continue
        answerable = question.get("answerable") is not False
        if answerable and not str(question.get("expected_answer") or "").strip():
            errors.append(f"question {index}: expected answer missing")
        evidence = str(question.get("evidence") or "").strip()
        evidence_case = evidence.split(":", 1)[0]
        if answerable and evidence_case not in case_ids:
            errors.append(f"question {index}: valid evidence case missing")
    for kind, count in specialist_counts.items():
        if count < 10:
            errors.append(f"specialists: expected at least 10 {kind} cases, got {count}")
    return {
        "documents": len(cases),
        "reviewed_documents": sum(
            isinstance(documents.get(str(case["case_id"])), dict)
            and documents[str(case["case_id"])].get("reviewed") is True
            for case in cases
        ),
        "document_units": unit_count,
        "specialists": specialist_counts,
        "questions": len(questions),
        "errors": errors,
        "valid": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate human annotations for the archive corpus.")
    parser.add_argument("--manifest", default="tests/gold/archive_corpus.tsv")
    parser.add_argument("--annotations", default="tests/gold/archive_human_annotations.json")
    args = parser.parse_args()
    report = validate_annotations(load_cases(Path(args.manifest)), load_annotations(Path(args.annotations)))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
