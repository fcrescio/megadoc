#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.archive_annotation_server import load_annotations, load_cases, normalize_page_spec


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
        entities = annotation.get("entities")
        if isinstance(entities, list):
            for entity_index, entity in enumerate(entities, start=1):
                if not isinstance(entity, dict):
                    errors.append(f"{case_id}: entity {entity_index} uses legacy untyped format")
                elif entity.get("entity_type") in {None, "", "unknown"} or not str(entity.get("value") or "").strip():
                    errors.append(f"{case_id}: entity {entity_index} type/value missing")
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
                specialist = unit.get("specialist")
                if isinstance(specialist, dict) and specialist.get("kind") in specialist_counts:
                    kind = str(specialist["kind"])
                    specialist_counts[kind] += 1
                    required = (
                        ("payable_kind", "issuer", "amount", "currency", "due_date", "payment_reference")
                        if kind == "payable" else ("table_pages",)
                    )
                    for field in required:
                        if not str(specialist.get(field) or "").strip():
                            errors.append(f"{case_id}: unit {index} {kind} field {field} missing")
                    if kind == "accounting":
                        table_pages = normalize_page_spec(
                            str(specialist.get("table_pages") or ""),
                            start_page=start,
                            end_page=end,
                        )
                        if not table_pages:
                            errors.append(f"{case_id}: unit {index} accounting table pages invalid")
                        gold_tables = specialist.get("gold_tables")
                        if specialist.get("tables_reviewed") is not True:
                            errors.append(f"{case_id}: unit {index} accounting tables not reviewed")
                        if not isinstance(gold_tables, list) or not gold_tables:
                            errors.append(f"{case_id}: unit {index} accounting gold tables missing")
                        else:
                            for table_index, table in enumerate(gold_tables, start=1):
                                if not isinstance(table, dict):
                                    errors.append(f"{case_id}: unit {index} gold table {table_index} invalid")
                                    continue
                                headers = table.get("headers")
                                rows = table.get("rows")
                                page = table.get("page_number")
                                if not isinstance(page, int) or not start <= page <= end:
                                    errors.append(f"{case_id}: unit {index} gold table {table_index} page invalid")
                                if not isinstance(headers, list) or not headers or any(not str(header).strip() for header in headers):
                                    errors.append(f"{case_id}: unit {index} gold table {table_index} headers invalid")
                                if not isinstance(rows, list) or not rows:
                                    errors.append(f"{case_id}: unit {index} gold table {table_index} rows missing")
                                elif isinstance(headers, list):
                                    for row_index, row in enumerate(rows, start=1):
                                        cells = row.get("cells") if isinstance(row, dict) else None
                                        if not isinstance(cells, dict) or set(cells) != set(headers):
                                            errors.append(f"{case_id}: unit {index} gold table {table_index} row {row_index} cells invalid")
                covered.extend(range(start, end + 1))
                unit_count += 1
            if sorted(covered) != list(range(1, page_count + 1)):
                errors.append(f"{case_id}: unit ranges must cover every page exactly once")
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
    data_root = Path(
        __import__("os").getenv(
            "MEGADOC_ARCHIVE_GOLD_DIR",
            str(Path.home() / ".local/share/megadoc/archive-gold"),
        )
    )
    parser = argparse.ArgumentParser(description="Validate human annotations for the archive corpus.")
    parser.add_argument("--manifest", default=str(data_root / "archive_corpus.tsv"))
    parser.add_argument("--annotations", default=str(data_root / "archive_human_annotations.json"))
    args = parser.parse_args()
    report = validate_annotations(load_cases(Path(args.manifest)), load_annotations(Path(args.annotations)))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
