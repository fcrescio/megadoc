#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for source_path in (
    ROOT / "packages" / "common" / "src",
):
    sys.path.insert(0, str(source_path))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from common.application.page_artifacts import add_page_artifacts_to_structured_json  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.db.models import OCRResult  # noqa: E402


def _has_materialized_page_artifacts(structured_json: Any) -> bool:
    return (
        isinstance(structured_json, dict)
        and isinstance(structured_json.get("page_artifacts"), list)
        and len(structured_json["page_artifacts"]) > 0
    )


def backfill(*, dry_run: bool, limit: int | None = None) -> dict[str, int]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    summary = {
        "scanned": 0,
        "already_present": 0,
        "updated": 0,
        "skipped_empty": 0,
    }
    with Session(engine) as session:
        stmt = select(OCRResult).order_by(OCRResult.created_at.asc(), OCRResult.id.asc())
        if limit is not None:
            stmt = stmt.limit(limit)
        results = session.execute(stmt).scalars().all()
        for ocr in results:
            summary["scanned"] += 1
            if _has_materialized_page_artifacts(ocr.structured_json):
                summary["already_present"] += 1
                continue
            structured = add_page_artifacts_to_structured_json(
                structured_json=ocr.structured_json,
                markdown_text=ocr.markdown_text,
                full_text=ocr.full_text,
                page_count=ocr.page_count,
                engine_name=ocr.engine_name,
                engine_version=ocr.engine_version,
                confidence_summary=ocr.confidence_summary,
            )
            artifacts = structured.get("page_artifacts")
            if not isinstance(artifacts, list) or not artifacts:
                summary["skipped_empty"] += 1
                continue
            if not dry_run:
                ocr.structured_json = structured
            summary["updated"] += 1
        if dry_run:
            session.rollback()
        else:
            session.commit()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill OCRResult structured_json.page_artifacts.")
    parser.add_argument("--dry-run", action="store_true", help="Compute updates without writing to the database.")
    parser.add_argument("--limit", type=int, default=None, help="Optional number of OCR rows to scan.")
    args = parser.parse_args()
    summary = backfill(dry_run=args.dry_run, limit=args.limit)
    for key, value in summary.items():
        print(f"{key}: {value}")
    if summary["skipped_empty"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
