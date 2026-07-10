#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
for source_path in (
    ROOT / "packages" / "common" / "src",
):
    sys.path.insert(0, str(source_path))

from sqlalchemy import create_engine, func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from common.config import get_settings  # noqa: E402
from common.db.models import (  # noqa: E402
    CanonicalEntity,
    CanonicalEntityVariant,
    DocumentUnit,
    DocumentUnitEntity,
    ScanUnit,
)


@dataclass(frozen=True)
class Candidate:
    entity_type: str
    entity_key: str
    display_value: str
    document_count: int
    mention_count: int


def normalized_entity_key(entity: DocumentUnitEntity) -> str:
    return (entity.normalized_value or entity.entity_value).strip().lower()


def choose_display_value(values: Iterable[str]) -> str:
    counter = Counter(value.strip() for value in values if value and value.strip())
    if not counter:
        return "unknown"
    return sorted(counter.items(), key=lambda item: (-item[1], len(item[0]), item[0].lower()))[0][0]


def collect_candidates(session: Session, *, min_documents: int) -> list[Candidate]:
    rows = (
        session.execute(
            select(DocumentUnitEntity, ScanUnit.source_document_id)
            .join(DocumentUnit, DocumentUnit.id == DocumentUnitEntity.document_unit_id)
            .join(ScanUnit, ScanUnit.id == DocumentUnit.scan_unit_id)
            .order_by(DocumentUnitEntity.created_at.asc())
        )
        .all()
    )
    grouped: dict[tuple[str, str], list[tuple[DocumentUnitEntity, object]]] = defaultdict(list)
    for entity, source_document_id in rows:
        key = normalized_entity_key(entity)
        if not key:
            continue
        grouped[(entity.entity_type, key)].append((entity, source_document_id))

    candidates: list[Candidate] = []
    for (entity_type, entity_key), group in grouped.items():
        document_ids = {source_document_id for _, source_document_id in group}
        if len(document_ids) < min_documents:
            continue
        candidates.append(
            Candidate(
                entity_type=entity_type,
                entity_key=entity_key,
                display_value=choose_display_value(entity.entity_value for entity, _ in group),
                document_count=len(document_ids),
                mention_count=len(group),
            )
        )
    return sorted(candidates, key=lambda item: (item.entity_type, item.entity_key))


def backfill(*, dry_run: bool, min_documents: int) -> dict[str, int]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    summary = {
        "candidates": 0,
        "created_entities": 0,
        "created_variants": 0,
        "already_present": 0,
    }
    with Session(engine) as session:
        candidates = collect_candidates(session, min_documents=min_documents)
        summary["candidates"] = len(candidates)
        for candidate in candidates:
            existing_variant = session.execute(
                select(CanonicalEntityVariant).where(
                    CanonicalEntityVariant.entity_type == candidate.entity_type,
                    CanonicalEntityVariant.entity_key == candidate.entity_key,
                )
            ).scalar_one_or_none()
            if existing_variant is not None:
                summary["already_present"] += 1
                continue
            existing_entity = session.execute(
                select(CanonicalEntity).where(
                    CanonicalEntity.entity_type == candidate.entity_type,
                    CanonicalEntity.canonical_value == candidate.entity_key,
                )
            ).scalar_one_or_none()
            if existing_entity is None:
                existing_entity = CanonicalEntity(
                    entity_type=candidate.entity_type,
                    canonical_value=candidate.entity_key,
                    display_value=candidate.display_value,
                    review_status="auto",
                )
                if not dry_run:
                    session.add(existing_entity)
                    session.flush()
                summary["created_entities"] += 1
            if not dry_run:
                session.add(
                    CanonicalEntityVariant(
                        canonical_entity_id=existing_entity.id,
                        entity_type=candidate.entity_type,
                        entity_key=candidate.entity_key,
                        display_value=candidate.display_value,
                        review_status="auto",
                    )
                )
            summary["created_variants"] += 1
        if dry_run:
            session.rollback()
        else:
            session.commit()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill canonical entities from repeated local entity keys.")
    parser.add_argument("--dry-run", action="store_true", help="Compute updates without writing to the database.")
    parser.add_argument(
        "--min-documents",
        type=int,
        default=2,
        help="Minimum number of distinct source documents required for automatic canonicalization.",
    )
    args = parser.parse_args()
    summary = backfill(dry_run=args.dry_run, min_documents=args.min_documents)
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
