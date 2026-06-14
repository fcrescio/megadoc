"""Deterministic title generation for document units.

Titles are derived from document type, specialist results, and entities.
No LLM calls — rules are purely heuristic and deterministic.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Human-readable labels for document type codes
DOCUMENT_TYPE_LABELS: dict[str, str] = {
    "bolletta": "Bolletta",
    "fattura": "Fattura",
    "verbale_assemblea": "Verbale assemblea",
    "regolamento_condominiale": "Regolamento condominiale",
    "rendiconto_contabile": "Rendiconto contabile",
    "riparto_spese": "Riparto spese",
    "preventivo": "Preventivo",
    "contratto": "Contratto",
    "lettera": "Lettera",
    "allegato_tecnico": "Allegato tecnico",
    "altro": "Documento",
}

# Mapping from specialist_type to a human-readable document family label
SPECIALIST_FAMILY_LABELS: dict[str, str] = {
    "utility_bill": "Bolletta",
    "accounting_statement": "Rendiconto",
}


def _get_type_label(document_type_code: str | None) -> str:
    """Return a human-readable label for a document type code."""
    if document_type_code and document_type_code in DOCUMENT_TYPE_LABELS:
        return DOCUMENT_TYPE_LABELS[document_type_code]
    return "Documento"


def _extract_entity(
    entities: list[Any],
    entity_type: str,
) -> str | None:
    """Return the first normalized or raw value for a given entity type."""
    for e in entities:
        etype = getattr(e, "entity_type", None) or (e.get("entity_type") if isinstance(e, dict) else None)
        if etype != entity_type:
            continue
        normalized = getattr(e, "normalized_value", None) or (e.get("normalized_value") if isinstance(e, dict) else None)
        if normalized:
            return normalized
        raw = getattr(e, "entity_value", None) or (e.get("entity_value") if isinstance(e, dict) else None)
        if raw:
            return raw
    return None


def _format_period(period_from: str | None, period_to: str | None) -> str | None:
    """Format a billing/accounting period into a short label."""
    if period_from and period_to:
        if period_from[:7] == period_to[:7]:
            return period_from[:7]  # same month: "2024-01"
        return f"{period_from[:7]}/{period_to[:7]}"
    if period_from:
        return period_from[:7]
    if period_to:
        return period_to[:7]
    return None


def _format_date(date_str: str | None) -> str | None:
    """Format a date string to YYYY-MM or just return as-is if short."""
    if not date_str:
        return None
    return date_str[:10]


def derive_document_unit_title(
    document_type_code: str | None = None,
    summary: str | None = None,
    entities: list[Any] | None = None,
    specialist_results: list[Any] | None = None,
    fallback_filename: str | None = None,
    page_range: tuple[int, int] | None = None,
) -> str:
    """Generate a deterministic title for a document unit.

    Rules are applied in order of specificity:

    1. **Utility bill**: ``Bolletta <issuer> - <account_holder> - <period/due_date>``
    2. **Accounting statement**: ``<statement_type> - <condominium/context> - <period>``
    3. **Meeting minutes**: ``Verbale assemblea - <condominium/context> - <date>``
    4. **Regulation**: ``Regolamento condominiale - <condominium/address>``
    5. **Generic with entities**: ``<type_label> - <primary_entity> - <page_range>``
    6. **Fallback**: ``<type_label> - pagine X-Y`` or just ``<type_label>``
    """
    entities = entities or []
    specialist_results = specialist_results or []

    type_label = _get_type_label(document_type_code)

    # --- Try specialist-driven titles first ---
    latest_by_type: dict[str, Any] = {}
    for sr in sorted(specialist_results, key=lambda x: getattr(x, "created_at", None) or "", reverse=True):
        stype = getattr(sr, "specialist_type", None) or (sr.get("specialist_type") if isinstance(sr, dict) else None)
        if stype and stype not in latest_by_type:
            latest_by_type[stype] = sr

    for specialist_type, result in latest_by_type.items():
        payload = getattr(result, "result_json", None) or (result.get("result_json") if isinstance(result, dict) else {})
        if not payload:
            continue

        if specialist_type == "utility_bill":
            title = _build_utility_bill_title(payload, entities, type_label)
            if title:
                return title

        if specialist_type == "accounting_statement":
            title = _build_accounting_title(payload, entities, type_label)
            if title:
                return title

    # --- Entity-driven titles ---
    organizzazione = _extract_entity(entities, "organizzazione") or _extract_entity(entities, "fornitore")
    persona = _extract_entity(entities, "persona")
    indirizzo = _extract_entity(entities, "indirizzo")

    if document_type_code == "verbale_assemblea":
        context = organizzazione or indirizzo or ""
        if context:
            return f"Verbale assemblea - {_clean(context)}"
        return "Verbale assemblea"

    if document_type_code == "regolamento_condominiale":
        context = organizzazione or indirizzo or ""
        if context:
            return f"Regolamento condominiale - {_clean(context)}"
        return "Regolamento condominiale"

    # --- Generic with primary entity ---
    primary = organizzazione or persona
    if primary:
        page_suffix = _page_suffix(page_range)
        return f"{type_label} - {_clean(primary)}{page_suffix}"

    # --- Fallback ---
    if page_range:
        return f"{type_label} - pagine {page_range[0]}-{page_range[1]}"
    return type_label


def _build_utility_bill_title(
    payload: dict[str, Any],
    entities: list[Any],
    type_label: str,
) -> str | None:
    """Build title for a utility bill specialist result."""
    issuer = payload.get("issuer") or ""
    account_holder = payload.get("account_holder") or ""
    period = _format_period(payload.get("billing_period_from"), payload.get("billing_period_to"))
    due_date = _format_date(payload.get("due_date"))

    # Clean up issuer — take the first meaningful part before "/" or ","
    issuer_short = _shorten_issuer(issuer) if issuer else ""

    parts = [type_label]
    if issuer_short:
        parts.append(issuer_short)
    if account_holder:
        parts.append(_clean(account_holder))
    period_str = period or due_date
    if period_str:
        parts.append(period_str)

    return " - ".join(parts)


def _build_accounting_title(
    payload: dict[str, Any],
    entities: list[Any],
    type_label: str,
) -> str | None:
    """Build title for an accounting statement specialist result."""
    statement_type = payload.get("statement_type") or ""
    statement_label = _accounting_statement_label(statement_type)

    period = _format_period(payload.get("accounting_period_from"), payload.get("accounting_period_to"))

    # Try to find condominium context from entities
    organizzazione = _extract_entity(entities, "organizzazione")
    indirizzo = _extract_entity(entities, "indirizzo")
    context = organizzazione or indirizzo or ""

    parts = [statement_label or type_label]
    if context:
        parts.append(_clean(context))
    if period:
        parts.append(period)

    return " - ".join(parts)


def _accounting_statement_label(statement_type: str) -> str:
    """Map internal statement_type codes to human-readable labels."""
    mapping = {
        "rendiconto_contabile": "Rendiconto contabile",
        "rendiconto_composito": "Rendiconto contabile",
        "consuntivo": "Consuntivo",
        "preventivo": "Preventivo",
        "riparto_spese": "Riparto spese",
        "bilancio": "Bilancio",
        "nota_credito": "Nota di credito",
        "estratto_conto": "Estratto conto",
    }
    return mapping.get(statement_type, statement_type.replace("_", " ").title())


def _shorten_issuer(issuer: str) -> str:
    """Shorten a long issuer name to its core identifier."""
    # Take the part before "/" or "," — usually the main brand
    for sep in [" / ", ", ", " - "]:
        if sep in issuer:
            return issuer.split(sep)[0].strip()
    return issuer.strip()


def _clean(value: str) -> str:
    """Normalize a value for use in a title: strip, capitalize first letter."""
    value = value.strip()
    if not value:
        return value
    # Capitalize first letter if it starts with lowercase
    if value[0].islower():
        value = value[0].upper() + value[1:]
    return value


def _page_suffix(page_range: tuple[int, int] | None) -> str:
    """Return a page-range suffix if the range is meaningful."""
    if page_range is None:
        return ""
    start, end = page_range
    if start == end:
        return ""
    return f" - pagine {start}-{end}"
