#!/usr/bin/env python3
"""Backfill document unit titles for existing records.

Usage:
    python scripts/backfill_document_unit_titles.py --dry-run
    python scripts/backfill_document_unit_titles.py --apply

The dry-run mode prints document_unit_id, old title, new title, and reason.
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload

from common.db.models import DocumentUnit, DocumentType

# Add the knowledge_classifier package to path so we can import title_generation
sys.path.insert(0, "services/knowledge_classifier/src")

from knowledge_classifier.services.title_generation import derive_document_unit_title  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = "postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc"


def get_document_units_without_titles(session: Session) -> list:
    """Fetch document units that have no title set."""
    return list(
        session.execute(
            select(DocumentUnit)
            .where(
                (DocumentUnit.title.is_(None)) | (DocumentUnit.title == "")
            )
            .options(
                selectinload(DocumentUnit.document_type),
                selectinload(DocumentUnit.entities),
                selectinload(DocumentUnit.specialist_results),
            )
            .order_by(DocumentUnit.created_at.asc())
        ).scalars().all()
    )


def generate_title(doc_unit) -> str:
    """Generate a title for a document unit using the shared helper."""
    document_type_code = None
    if doc_unit.document_type is not None:
        document_type_code = doc_unit.document_type.code

    return derive_document_unit_title(
        document_type_code=document_type_code,
        summary=doc_unit.extracted_summary,
        entities=list(doc_unit.entities),
        specialist_results=list(doc_unit.specialist_results),
        page_range=(doc_unit.start_page, doc_unit.end_page),
    )


def main():
    parser = argparse.ArgumentParser(description="Backfill document unit titles")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without applying them",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply title changes to the database",
    )
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.print_help()
        sys.exit(1)

    engine = create_engine(DATABASE_URL)

    with Session(engine) as session:
        units = get_document_units_without_titles(session)
        logger.info("Found %d document units without titles", len(units))

        updated_count = 0
        skipped_count = 0

        for doc_unit in units:
            old_title = doc_unit.title or "(empty)"
            new_title = generate_title(doc_unit)

            if not new_title or new_title == old_title:
                skipped_count += 1
                continue

            print(
                f"  {doc_unit.id}: "
                f"'{old_title[:60]}' -> '{new_title[:80]}'"
            )

            if args.apply:
                doc_unit.title = new_title[:512]
                updated_count += 1

        if args.apply:
            session.flush()
            session.commit()
            logger.info("Updated %d titles, skipped %d", updated_count, skipped_count)
        else:
            logger.info(
                "Dry-run: %d would be updated, %d skipped. Use --apply to persist.",
                updated_count,
                skipped_count,
            )


if __name__ == "__main__":
    main()
