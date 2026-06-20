#!/usr/bin/env python3
"""Read-only cleanup report for topic backlog.

Finds candidate groups for merge/review:
  - Topics with 0 or 1 assignments (near-orphans)
  - Topics with identical or near-identical titles (normalized)
  - Topics sharing the same dominant archive_identity axes
  - Probable typos against canonical entities
  - Topics with topic_kind incompatible with dominant document_family

Usage:
    python scripts/topic_cleanup_report.py
    python scripts/topic_cleanup_report.py --json tmp/topic_cleanup.json
    python scripts/topic_cleanup_report.py --min-similarity 0.85
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

sys.path.insert(0, "packages/common/src")

from common.db.models import (  # noqa: E402
    DocumentUnit,
    DocumentUnitTopicAssignment,
    Topic,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATABASE_URL = "postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc"


def _normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^\w\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


def _dominant_family_for_topic(session: Session, topic_id: str) -> str | None:
    rows = (
        session.execute(
            select(DocumentUnit.archive_identity_json)
            .join(DocumentUnitTopicAssignment, DocumentUnitTopicAssignment.document_unit_id == DocumentUnit.id)
            .where(DocumentUnitTopicAssignment.topic_id == topic_id)
            .where(DocumentUnit.archive_identity_json.isnot(None))
        )
        .scalars()
        .all()
    )
    families = []
    for row in rows:
        if row and isinstance(row, dict):
            f = row.get("document_family")
            if f:
                families.append(f)
    if not families:
        return None
    # Deterministic tie-break: (count DESC, value ASC)
    counts = Counter(families)
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def find_near_orphans(session: Session) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    topics = session.execute(
        select(Topic).where(Topic.is_active.is_(True)).order_by(Topic.title.asc())
    ).scalars().all()

    for topic in topics:
        count = (
            session.execute(
                select(func.count(DocumentUnitTopicAssignment.id))
                .where(DocumentUnitTopicAssignment.topic_id == topic.id)
            ).scalar() or 0
        )
        if count <= 1:
            results.append({
                "topic_id": str(topic.id),
                "title": topic.title,
                "slug": topic.slug,
                "topic_kind": topic.topic_kind,
                "topic_class": topic.topic_class,
                "assignment_count": count,
                "category": "near_orphan",
                "note": f"Solo {count} assegnazione(i)" if count == 1 else "Nessuna assegnazione",
            })
    return results


def find_duplicate_titles(session: Session, min_similarity: float = 0.90) -> list[dict[str, Any]]:
    topics = session.execute(
        select(Topic).where(Topic.is_active.is_(True)).order_by(Topic.title.asc())
    ).scalars().all()

    groups: list[list[Topic]] = []
    used: set[str] = set()

    for i, a in enumerate(topics):
        if str(a.id) in used:
            continue
        group = [a]
        used.add(str(a.id))
        for j, b in enumerate(topics):
            if str(b.id) in used:
                continue
            if _title_similarity(a.title, b.title) >= min_similarity:
                group.append(b)
                used.add(str(b.id))
        if len(group) > 1:
            groups.append(group)

    results: list[dict[str, Any]] = []
    for group in groups:
        results.append({
            "category": "duplicate_title",
            "similarity_threshold": min_similarity,
            "candidates": [
                {
                    "topic_id": str(t.id),
                    "title": t.title,
                    "slug": t.slug,
                    "topic_kind": t.topic_kind,
                }
                for t in group
            ],
            "note": f"{len(group)} topic con titoli simili",
        })
    return results


def find_shared_identity_axis(session: Session) -> list[dict[str, Any]]:
    topics = session.execute(
        select(Topic).where(Topic.is_active.is_(True)).order_by(Topic.title.asc())
    ).scalars().all()

    topic_axes: dict[str, dict[str, str | None]] = {}
    for topic in topics:
        rows = (
            session.execute(
                select(DocumentUnit.archive_identity_json)
                .join(DocumentUnitTopicAssignment, DocumentUnitTopicAssignment.document_unit_id == DocumentUnit.id)
                .where(DocumentUnitTopicAssignment.topic_id == topic.id)
                .where(DocumentUnit.archive_identity_json.isnot(None))
            )
            .scalars()
            .all()
        )
        axes: dict[str, list[str | None]] = defaultdict(list)
        for row in rows:
            if row and isinstance(row, dict):
                for key in ("context_key", "primary_party_key", "subject_key", "matter_key"):
                    val = row.get(key)
                    if val:
                        axes[key].append(val)
        dominant = {}
        for key, vals in axes.items():
            if vals:
                counts = Counter(vals)
                dominant[key] = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            else:
                dominant[key] = None
        topic_axes[str(topic.id)] = dominant

    axis_groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for tid, axes in topic_axes.items():
        for key in ("context_key", "primary_party_key"):
            val = axes.get(key)
            if val:
                axis_groups[f"{key}:{val}"].append((tid, val))

    results: list[dict[str, Any]] = []
    for axis_key, members in axis_groups.items():
        if len(members) < 2:
            continue
        topic_map = {str(t.id): t for t in topics}
        candidates = []
        for tid, _ in members:
            t = topic_map.get(tid)
            if t:
                candidates.append({
                    "topic_id": tid,
                    "title": t.title,
                    "slug": t.slug,
                    "topic_kind": t.topic_kind,
                })
        if len(candidates) >= 2:
            results.append({
                "category": "shared_identity_axis",
                "axis": axis_key,
                "candidates": candidates,
                "note": f"{len(candidates)} topic condividono {axis_key}",
            })
    return results


def find_typo_candidates(session: Session) -> list[dict[str, Any]]:
    topics = session.execute(
        select(Topic).where(Topic.is_active.is_(True)).order_by(Topic.title.asc())
    ).scalars().all()

    counts: dict[str, int] = {}
    for t in topics:
        counts[str(t.id)] = (
            session.execute(
                select(func.count(DocumentUnitTopicAssignment.id))
                .where(DocumentUnitTopicAssignment.topic_id == t.id)
            ).scalar() or 0
        )

    results: list[dict[str, Any]] = []
    used: set[str] = set()

    for a in topics:
        if str(a.id) in used:
            continue
        best_match = None
        best_score = 0.0
        for b in topics:
            if a.id == b.id or str(b.id) in used:
                continue
            score = _title_similarity(a.title, b.title)
            if 0.70 <= score < 0.95 and score > best_score:
                if counts.get(str(a.id), 0) < counts.get(str(b.id), 0):
                    best_match = b
                    best_score = score
                elif counts.get(str(b.id), 0) < counts.get(str(a.id), 0):
                    best_match = a
                    best_score = score
                    a, b = b, a

        if best_match and best_score >= 0.70:
            used.add(str(a.id))
            used.add(str(best_match.id))
            results.append({
                "category": "probable_typo",
                "similarity": round(best_score, 3),
                "typo_candidate": {
                    "topic_id": str(a.id),
                    "title": a.title,
                    "slug": a.slug,
                    "assignment_count": counts.get(str(a.id), 0),
                },
                "canonical_candidate": {
                    "topic_id": str(best_match.id),
                    "title": best_match.title,
                    "slug": best_match.slug,
                    "assignment_count": counts.get(str(best_match.id), 0),
                },
                "note": f"'{a.title}' potrebbe essere un typo di '{best_match.title}' (sim={best_score:.2f})",
            })

    return results


def find_kind_mismatch(session: Session) -> list[dict[str, Any]]:
    topics = session.execute(
        select(Topic).where(Topic.is_active.is_(True)).order_by(Topic.title.asc())
    ).scalars().all()

    FAMILY_KIND_MAP: dict[str, str] = {
        "utility_bill": "entity",
        "accounting_statement": "context",
        "meeting_minutes": "family",
        "meeting_agenda": "family",
        "legal_document": "issue",
        "regolamento": "context",
        "comunicazione": "context",
        "generic": "context",
    }

    results: list[dict[str, Any]] = []
    for topic in topics:
        dominant_family = _dominant_family_for_topic(session, str(topic.id))
        if not dominant_family:
            continue
        expected_kind = FAMILY_KIND_MAP.get(dominant_family)
        if expected_kind and topic.topic_kind != expected_kind:
            results.append({
                "category": "kind_mismatch",
                "topic_id": str(topic.id),
                "title": topic.title,
                "slug": topic.slug,
                "current_kind": topic.topic_kind,
                "dominant_family": dominant_family,
                "expected_kind": expected_kind,
                "note": f"topic_kind='{topic.topic_kind}' ma document_family dominante='{dominant_family}' (atteso '{expected_kind}')",
            })
    return results


def main():
    parser = argparse.ArgumentParser(description="Topic cleanup report")
    parser.add_argument("--json", type=str, default=None, help="Write JSON output to file")
    parser.add_argument(
        "--min-similarity", type=float, default=0.90,
        help="Minimum title similarity for duplicate detection (default: 0.90)",
    )
    args = parser.parse_args()

    engine = create_engine(DATABASE_URL)

    report: dict[str, Any] = {
        "generated_at": "unknown",
        "min_similarity": args.min_similarity,
        "categories": {},
        "summary": {},
    }

    with Session(engine) as session:
        total_topics = session.execute(
            select(func.count(Topic.id)).where(Topic.is_active.is_(True))
        ).scalar() or 0
        total_assignments = session.execute(
            select(func.count(DocumentUnitTopicAssignment.id))
        ).scalar() or 0

        logger.info("Active topics: %d, Total assignments: %d", total_topics, total_assignments)

        logger.info("Finding near-orphan topics...")
        near_orphans = find_near_orphans(session)
        report["categories"]["near_orphans"] = near_orphans
        logger.info("  Found %d near-orphan topics", len(near_orphans))

        logger.info("Finding duplicate titles (min_similarity=%.2f)...", args.min_similarity)
        duplicate_titles = find_duplicate_titles(session, args.min_similarity)
        report["categories"]["duplicate_titles"] = duplicate_titles
        logger.info("  Found %d duplicate title groups", len(duplicate_titles))

        logger.info("Finding topics sharing archive_identity axes...")
        shared_axis = find_shared_identity_axis(session)
        report["categories"]["shared_identity_axis"] = shared_axis
        logger.info("  Found %d shared-axis groups", len(shared_axis))

        logger.info("Finding probable typos...")
        typos = find_typo_candidates(session)
        report["categories"]["probable_typos"] = typos
        logger.info("  Found %d probable typo pairs", len(typos))

        logger.info("Finding topic_kind / document_family mismatches...")
        kind_mismatches = find_kind_mismatch(session)
        report["categories"]["kind_mismatches"] = kind_mismatches
        logger.info("  Found %d kind mismatches", len(kind_mismatches))

        report["summary"] = {
            "total_active_topics": total_topics,
            "total_assignments": total_assignments,
            "near_orphans_count": len(near_orphans),
            "duplicate_title_groups": len(duplicate_titles),
            "shared_axis_groups": len(shared_axis),
            "probable_typo_pairs": len(typos),
            "kind_mismatches_count": len(kind_mismatches),
        }

    output = json.dumps(report, indent=2, default=str)
    if args.json:
        with open(args.json, "w") as f:
            f.write(output)
        logger.info("Report written to %s", args.json)
    else:
        print(output)


if __name__ == "__main__":
    main()
