from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.db.models import RuntimeSetting


RUNTIME_ML_SETTING_KEYS = frozenset(
    {
        "llm_endpoint",
        "llm_model",
        "embedding_endpoint",
        "embedding_model",
        "ocr_vision_endpoint",
        "ocr_vision_model",
        "ocr_dots_endpoint",
        "ocr_dots_model",
    }
)


def load_runtime_settings(session: Session) -> dict[str, str]:
    rows = session.execute(
        select(RuntimeSetting).where(RuntimeSetting.key.in_(RUNTIME_ML_SETTING_KEYS))
    ).scalars()
    return {row.key: row.value for row in rows}


def resolve_runtime_settings(session: Session, defaults: Mapping[str, str]) -> dict[str, str]:
    values = dict(defaults)
    values.update(load_runtime_settings(session))
    return values


def save_runtime_settings(session: Session, values: Mapping[str, str]) -> None:
    invalid = set(values) - RUNTIME_ML_SETTING_KEYS
    if invalid:
        raise ValueError(f"Unsupported runtime settings: {', '.join(sorted(invalid))}")
    existing = {
        row.key: row
        for row in session.execute(
            select(RuntimeSetting).where(RuntimeSetting.key.in_(values))
        ).scalars()
    }
    for key, value in values.items():
        normalized = value.strip()
        if not normalized:
            raise ValueError(f"Runtime setting {key} cannot be empty")
        row = existing.get(key)
        if row is None:
            session.add(RuntimeSetting(key=key, value=normalized))
        else:
            row.value = normalized
