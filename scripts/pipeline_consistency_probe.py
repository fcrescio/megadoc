#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages/common/src"))

from sqlalchemy import create_engine, text  # noqa: E402

from common.config import get_settings  # noqa: E402


CHECKS = {
    "orphan_ocr_results": """
        SELECT count(*) FROM ocr_results o
        LEFT JOIN documents d ON d.id = o.document_id WHERE d.id IS NULL
    """,
    "orphan_scan_units": """
        SELECT count(*) FROM scan_units s
        LEFT JOIN ocr_results o ON o.id = s.source_ocr_result_id WHERE o.id IS NULL
    """,
    "orphan_document_units": """
        SELECT count(*) FROM document_units u
        LEFT JOIN scan_units s ON s.id = u.scan_unit_id WHERE s.id IS NULL
    """,
    "orphan_specialist_results": """
        SELECT count(*) FROM specialist_results r
        LEFT JOIN document_units u ON u.id = r.document_unit_id WHERE u.id IS NULL
    """,
    "duplicate_active_ingestion": """
        SELECT count(*) FROM (
            SELECT document_id, job_type FROM ingestion_jobs
            WHERE status IN ('queued', 'pending', 'running', 'processing')
            GROUP BY document_id, job_type HAVING count(*) > 1
        ) duplicates
    """,
    "duplicate_active_knowledge": """
        SELECT count(*) FROM (
            SELECT scan_unit_id, job_type FROM knowledge_jobs
            WHERE status IN ('queued', 'pending', 'running', 'processing')
            GROUP BY scan_unit_id, job_type HAVING count(*) > 1
        ) duplicates
    """,
    "duplicate_active_specialists": """
        SELECT count(*) FROM (
            SELECT document_unit_id, specialist_type FROM specialist_jobs
            WHERE status IN ('queued', 'pending', 'running', 'processing')
            GROUP BY document_unit_id, specialist_type HAVING count(*) > 1
        ) duplicates
    """,
}


def probe(database_url: str) -> dict:
    engine = create_engine(database_url)
    with engine.connect() as connection:
        counts = {
            table: int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
            for table in (
                "documents", "ocr_results", "scan_units", "document_units",
                "specialist_results", "knowledge_search_chunks",
            )
        }
        checks = {
            name: int(connection.execute(text(query)).scalar_one())
            for name, query in CHECKS.items()
        }
        job_status = {
            table: {
                row.status: int(row.count)
                for row in connection.execute(text(
                    f"SELECT status, count(*) AS count FROM {table} GROUP BY status ORDER BY status"
                )).mappings()
            }
            for table in ("ingestion_jobs", "knowledge_jobs", "specialist_jobs")
        }
    violations = {name: value for name, value in checks.items() if value != 0}
    return {
        "status": "consistent" if not violations else "inconsistent",
        "counts": counts,
        "job_status": job_status,
        "checks": checks,
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Megadoc consistency after restart or job replay.")
    parser.add_argument("--database-url", default=get_settings().database_url)
    args = parser.parse_args()
    result = probe(args.database_url)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "consistent" else 1


if __name__ == "__main__":
    raise SystemExit(main())
