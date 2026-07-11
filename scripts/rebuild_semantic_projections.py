#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "common" / "src"))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from common.application.projections import rebuild_semantic_projections  # noqa: E402
from common.config import get_settings  # noqa: E402


def rebuild(*, verify_idempotent: bool = False) -> dict[str, object]:
    engine = create_engine(get_settings().database_url)
    with Session(engine) as session:
        first = rebuild_semantic_projections(session)
        session.commit()
        result = {
            "graph": asdict(first.graph),
            "contexts": asdict(first.contexts),
            "fingerprint": first.fingerprint,
            "idempotent": None,
        }
        if verify_idempotent:
            second = rebuild_semantic_projections(session)
            session.commit()
            stable = first == second
            result["idempotent"] = stable
            if not stable:
                raise RuntimeError(
                    f"semantic projections are not idempotent: {first!r} != {second!r}"
                )
        return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild graph and context projections.")
    parser.add_argument(
        "--verify-idempotent",
        action="store_true",
        help="Rebuild twice and fail if semantic content or counts change.",
    )
    args = parser.parse_args()
    print(json.dumps(rebuild(verify_idempotent=args.verify_idempotent), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
