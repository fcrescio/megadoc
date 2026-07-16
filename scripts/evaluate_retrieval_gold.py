#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/common/src"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from common.config import get_settings  # noqa: E402
from common.db.models import Document  # noqa: E402


def parse_evidence(value: str) -> list[tuple[str, int, int]]:
    entries: list[tuple[str, int, int]] = []
    for raw_entry in value.replace(";", ",").replace("\n", ",").split(","):
        entry = raw_entry.strip()
        if not entry or ":" not in entry:
            continue
        case_id, raw_pages = entry.rsplit(":", 1)
        bounds = raw_pages.strip().split("-", 1)
        if not all(bound.strip().isdigit() for bound in bounds):
            continue
        page_from = int(bounds[0])
        page_to = int(bounds[-1])
        entries.append((case_id.strip(), min(page_from, page_to), max(page_from, page_to)))
    return entries


def percentile(values: list[float], percentile_value: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile_value * len(ordered)) - 1)
    return ordered[index]


def _matches_evidence(
    result: dict[str, Any],
    expected: set[tuple[str, int]],
) -> bool:
    document_id = str(result.get("document_id") or "")
    page_from = result.get("page_from")
    page_to = result.get("page_to") or page_from
    if not document_id or not isinstance(page_from, int) or not isinstance(page_to, int):
        return False
    return any((document_id, page) in expected for page in range(page_from, page_to + 1))


def evaluate(
    annotations_path: Path,
    *,
    database_url: str,
    api_base_url: str,
    min_questions: int = 30,
) -> dict[str, Any]:
    payload = json.loads(annotations_path.read_text(encoding="utf-8"))
    questions = [
        question
        for question in payload.get("questions", [])
        if isinstance(question, dict) and question.get("answerable") is not False
    ]
    if len(questions) < min_questions:
        return {
            "status": "insufficient_gold",
            "questions": len(questions),
            "required_questions": min_questions,
        }

    evidence_by_case: dict[str, str] = {}
    for question in questions:
        for case_id, _, _ in parse_evidence(str(question.get("evidence") or "")):
            evidence_by_case[case_id] = ""
    engine = create_engine(database_url)
    with Session(engine) as session:
        documents = session.execute(
            select(Document).where(Document.external_id.in_(evidence_by_case))
        ).scalars().all()
    document_ids = {str(document.external_id): str(document.id) for document in documents}

    cases: list[dict[str, Any]] = []
    latencies: list[float] = []
    for index, question in enumerate(questions, start=1):
        expected: set[tuple[str, int]] = set()
        unresolved: list[str] = []
        for case_id, page_from, page_to in parse_evidence(str(question.get("evidence") or "")):
            document_id = document_ids.get(case_id)
            if not document_id:
                unresolved.append(case_id)
                continue
            expected.update((document_id, page) for page in range(page_from, page_to + 1))
        started = time.monotonic()
        url = f"{api_base_url.rstrip('/')}/knowledge/search/evidence?{urlencode({'q': question['question'], 'limit': 10})}"
        with urlopen(url, timeout=180) as response:
            result = json.load(response)
        latency = time.monotonic() - started
        latencies.append(latency)
        ranked = result.get("results", [])
        first_rank = next(
            (rank for rank, candidate in enumerate(ranked, start=1) if _matches_evidence(candidate, expected)),
            None,
        )
        cases.append({
            "index": index,
            "question": question["question"],
            "first_relevant_rank": first_rank,
            "recall_at_5": first_rank is not None and first_rank <= 5,
            "recall_at_10": first_rank is not None and first_rank <= 10,
            "latency_seconds": round(latency, 3),
            "unresolved_case_ids": unresolved,
            "warnings": result.get("warnings", []),
        })

    count = len(cases)
    recall_at_5 = sum(case["recall_at_5"] for case in cases) / count
    recall_at_10 = sum(case["recall_at_10"] for case in cases) / count
    p50 = percentile(latencies, 0.50)
    p95 = percentile(latencies, 0.95)
    targets_met = recall_at_5 >= 0.90 and recall_at_10 >= 0.95 and bool(p95 is not None and p95 < 2.0)
    return {
        "status": "passed" if targets_met else "failed",
        "questions": count,
        "recall_at_5": round(recall_at_5, 4),
        "recall_at_10": round(recall_at_10, 4),
        "latency_p50_seconds": round(p50, 3) if p50 is not None else None,
        "latency_p95_seconds": round(p95, 3) if p95 is not None else None,
        "targets": {"recall_at_5": 0.90, "recall_at_10": 0.95, "latency_p95_seconds_lt": 2.0},
        "cases": cases,
    }


def main() -> int:
    data_root = Path(os.getenv("MEGADOC_ARCHIVE_GOLD_DIR", str(Path.home() / ".local/share/megadoc/archive-gold")))
    parser = argparse.ArgumentParser(description="Measure evidence retrieval against private archive questions.")
    parser.add_argument("--annotations", default=str(data_root / "archive_human_annotations.json"))
    parser.add_argument("--database-url", default=get_settings().database_url)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--min-questions", type=int, default=30)
    args = parser.parse_args()
    report = evaluate(
        Path(args.annotations),
        database_url=args.database_url,
        api_base_url=args.api_base_url,
        min_questions=args.min_questions,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
