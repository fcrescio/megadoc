#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "common" / "src"))

from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import Session, selectinload  # noqa: E402

from common.application.calendar import project_utility_bill_calendar_event  # noqa: E402
from common.application.payables import project_payable  # noqa: E402
from common.config import get_settings  # noqa: E402
from common.db.models import DocumentUnit, SpecialistResult  # noqa: E402


def backfill(*, dry_run: bool = False) -> dict[str, int]:
    engine = create_engine(get_settings().database_url)
    stats = {"results": 0, "payables": 0, "calendar_events": 0}
    with Session(engine) as session:
        results = session.execute(
            select(SpecialistResult)
            .where(SpecialistResult.specialist_type == "utility_bill")
            .options(
                selectinload(SpecialistResult.document_unit).selectinload(DocumentUnit.document_type)
            )
            .order_by(SpecialistResult.created_at.asc())
        ).scalars().all()
        for result in results:
            stats["results"] += 1
            payable = project_payable(session, result.document_unit, result)
            if payable is not None:
                stats["payables"] += 1
            if project_utility_bill_calendar_event(session, result.document_unit, result) is not None:
                stats["calendar_events"] += 1
        if dry_run:
            session.rollback()
        else:
            session.commit()
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Project existing utility results into payables.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(backfill(dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
