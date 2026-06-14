#!/usr/bin/env python3
"""Backfill archive_identity_json for existing document units.

Usage:
    python scripts/backfill_archive_identity.py --dry-run
    python scripts/backfill_archive_identity.py --apply

The dry-run mode prints document_unit_id and the identity that would be set.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload

from common.db.models import DocumentUnit

sys.path.insert(0, "services/knowledge_classifier/src")

from knowledge_classifier.services.archive_identity import derive_archive_identity  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = "postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc"


def get_all_document_units(session: Session) -> list:
    """Fetch all document units with their entities and specialist results."""
    return list(
        session.execute(
            select(DocumentUnit)
            .options(
                selectinload(DocumentUnit.document_type),
                selectinload(DocumentUnit.entities),
                selectinload(DocumentUnit.specialist_results),
            )
            .order_by(DocumentUnit.created_at.asc())
        ).scalars().all()
    )


def main():
    parser = argparse.ArgumentParser(description="Backfill archive identity for document units")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without applying them")
    parser.add_argument("--apply", action="store_true", help="Apply identity changes to the database")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        parser.print_help()
        sys.exit(1)

    engine = create_engine(DATABASE_URL)

    with Session(engine) as session:
        units = get_all_document_units(session)
        logger.info("Found %d document units", len(units))

        updated_count = 0
        skipped_count = 0

        for doc_unit in units:
            document_type_code = None
            if doc_unit.document_type is not None:
                document_type_code = doc_unit.document_type.code

            identity = derive_archive_identity(
                document_type_code=document_type_code,
                entities=list(doc_unit.entities),
                specialist_results=list(doc_unit.specialist_results),
            )

            old_identity = doc_unit.archive_identity_json
            if identity == old_identity:
                skipped_count += 1
                continue

            family = identity.get("document_family") if identity else "None"
            context = identity.get("context_key") if identity else "None"
            confidence = identity.get("confidence") if identity else 0.0
            print(f"  {doc_unit.id}: family={family} context={context} confidence={confidence}")

            if args.apply:
                doc_unit.archive_identity_json = identity
                updated_count += 1

        if args.apply:
            session.flush()
            session.commit()
            logger.info("Updated %d identities, skipped %d", updated_count, skipped_count)
        else:
            logger.info(
                "Dry-run: %d would be updated, %d skipped. Use --apply to persist.",
                updated_count,
                skipped_count,
            )


if __name__ == "__main__":
    main()
