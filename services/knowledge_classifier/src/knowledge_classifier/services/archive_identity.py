"""Deterministic archive identity derivation for document units.

Archive identity is a JSON structure that captures the key archival axes
of a document unit: document family, context, primary party, subject,
period, and matter. This enables matching across documents without
relying solely on titles or topic overlap.

No LLM calls — rules are purely heuristic and deterministic.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Mapping from document_type_code to document_family
DOCUMENT_TYPE_FAMILY: dict[str, str] = {
    "bolletta": "utility_bill",
    "fattura": "invoice",
    "verbale_assemblea": "meeting_minutes",
    "regolamento_condominiale": "regulation",
    "rendiconto_contabile": "accounting_statement",
    "riparto_spese": "expense_allocation",
    "preventivo": "quote",
    "contratto": "contract",
    "lettera": "correspondence",
    "allegato_tecnico": "technical_attachment",
    "altro": "other",
}

# Specialist types that override document_family
SPECIALIST_FAMILY: dict[str, str] = {
    "utility_bill": "utility_bill",
    "accounting_statement": "accounting_statement",
}


def _extract_entity_value(
    entities: list[Any],
    entity_type: str,
    prefer_normalized: bool = True,
) -> str | None:
    """Return the first value for a given entity type."""
    for e in entities:
        etype = getattr(e, "entity_type", None) or (e.get("entity_type") if isinstance(e, dict) else None)
        if etype != entity_type:
            continue
        if prefer_normalized:
            normalized = getattr(e, "normalized_value", None) or (e.get("normalized_value") if isinstance(e, dict) else None)
            if normalized:
                return normalized
        raw = getattr(e, "entity_value", None) or (e.get("entity_value") if isinstance(e, dict) else None)
        if raw:
            return raw
    return None


def _extract_all_entity_values(
    entities: list[Any],
    entity_type: str,
    prefer_normalized: bool = True,
) -> list[str]:
    """Return all values for a given entity type."""
    values: list[str] = []
    for e in entities:
        etype = getattr(e, "entity_type", None) or (e.get("entity_type") if isinstance(e, dict) else None)
        if etype != entity_type:
            continue
        if prefer_normalized:
            val = getattr(e, "normalized_value", None) or (e.get("normalized_value") if isinstance(e, dict) else None)
            if val:
                values.append(val)
                continue
        raw = getattr(e, "entity_value", None) or (e.get("entity_value") if isinstance(e, dict) else None)
        if raw:
            values.append(raw)
    return values


def _build_context_key(entities: list[Any]) -> str | None:
    """Build a context key from strong entities (condominium, address, place)."""
    # Prefer condominium-like organizations
    orgs = _extract_all_entity_values(entities, "organizzazione")
    for org in orgs:
        org_lower = org.lower().replace("_", " ")
        if "condominio" in org_lower:
            return f"condominio:{org}"

    # Fall back to address
    addresses = _extract_all_entity_values(entities, "indirizzo")
    places = _extract_all_entity_values(entities, "luogo")
    if addresses and places:
        return f"address:{addresses[0]}_{places[0]}"
    if addresses:
        return f"address:{addresses[0]}"

    # Fall back to any organization
    if orgs:
        return f"organization:{orgs[0]}"

    return None


def _build_primary_party_key(entities: list[Any], specialist_results: list[Any]) -> str | None:
    """Build a primary party key from specialist results or entities."""
    # Try specialist results first
    for sr in specialist_results:
        payload = getattr(sr, "result_json", None) or (sr.get("result_json") if isinstance(sr, dict) else {})
        if not payload:
            continue
        issuer = payload.get("issuer")
        if issuer:
            return f"organization:{issuer.strip().lower().replace(' ', '_')}"

    # Fall back to organizzazione entities
    org = _extract_entity_value(entities, "organizzazione")
    if org:
        return f"organization:{org}"

    return None


def _build_subject_key(entities: list[Any], specialist_results: list[Any]) -> str | None:
    """Build a subject key from specialist results or entities."""
    # Try specialist results first
    for sr in specialist_results:
        payload = getattr(sr, "result_json", None) or (sr.get("result_json") if isinstance(sr, dict) else {})
        if not payload:
            continue
        account_holder = payload.get("account_holder")
        if account_holder:
            return f"person:{account_holder.strip().lower().replace(' ', '_')}"

    # Fall back to persona entities
    person = _extract_entity_value(entities, "persona")
    if person:
        return f"person:{person}"

    return None


def _build_period_key(specialist_results: list[Any]) -> str | None:
    """Build a period key from specialist results."""
    for sr in specialist_results:
        payload = getattr(sr, "result_json", None) or (sr.get("result_json") if isinstance(sr, dict) else {})
        if not payload:
            continue
        # Try billing period
        period_from = payload.get("billing_period_from") or payload.get("accounting_period_from")
        period_to = payload.get("billing_period_to") or payload.get("accounting_period_to")
        if period_from and period_to:
            if period_from[:7] == period_to[:7]:
                return period_from[:7]
            return f"{period_from[:7]}/{period_to[:7]}"
        if period_from:
            return period_from[:7]
        if period_to:
            return period_to[:7]
        # Try due date or issue date as fallback
        for date_field in ("due_date", "issue_date"):
            date_val = payload.get(date_field)
            if date_val:
                return date_val[:7]
    return None


def _compute_confidence(
    document_family: str | None,
    context_key: str | None,
    primary_party_key: str | None,
    subject_key: str | None,
    period_key: str | None,
    has_specialist: bool,
) -> float:
    """Compute overall confidence for the archive identity."""
    filled = sum(1 for k in [document_family, context_key, primary_party_key, subject_key, period_key] if k)
    if has_specialist and filled >= 4:
        return 0.85
    if has_specialist and filled >= 3:
        return 0.75
    if filled >= 3:
        return 0.65
    if filled >= 2:
        return 0.50
    if filled >= 1:
        return 0.35
    return 0.15


def derive_archive_identity(
    document_type_code: str | None = None,
    entities: list[Any] | None = None,
    specialist_results: list[Any] | None = None,
) -> dict[str, Any] | None:
    """Derive archive identity for a document unit.

    Returns a dict with archive identity keys, or None if no data is available.

    The returned dict has the following structure:
    {
        "document_family": str,
        "context_key": str | None,
        "primary_party_key": str | None,
        "subject_key": str | None,
        "period_key": str | None,
        "matter_key": None,
        "confidence": float,
        "evidence": {
            "document_type": str | None,
            "specialist_types": [str, ...],
            "entity_types": [str, ...],
        }
    }
    """
    entities = entities or []
    specialist_results = specialist_results or []

    # Determine document_family
    document_family = DOCUMENT_TYPE_FAMILY.get(document_type_code or "") if document_type_code else None

    # Override with specialist family if available
    for sr in specialist_results:
        stype = getattr(sr, "specialist_type", None) or (sr.get("specialist_type") if isinstance(sr, dict) else None)
        if stype and stype in SPECIALIST_FAMILY:
            document_family = SPECIALIST_FAMILY[stype]
            break

    # Build axes
    context_key = _build_context_key(entities)
    primary_party_key = _build_primary_party_key(entities, specialist_results)
    subject_key = _build_subject_key(entities, specialist_results)
    period_key = _build_period_key(specialist_results)

    has_specialist = bool(specialist_results)
    confidence = _compute_confidence(
        document_family, context_key, primary_party_key, subject_key, period_key, has_specialist
    )

    # Collect evidence
    specialist_types = list({
        getattr(sr, "specialist_type", None) or (sr.get("specialist_type") if isinstance(sr, dict) else None)
        for sr in specialist_results
        if (getattr(sr, "specialist_type", None) or (sr.get("specialist_type") if isinstance(sr, dict) else None))
    })
    entity_types = list({
        getattr(e, "entity_type", None) or (e.get("entity_type") if isinstance(e, dict) else None)
        for e in entities
        if (getattr(e, "entity_type", None) or (e.get("entity_type") if isinstance(e, dict) else None))
    })

    identity: dict[str, Any] = {
        "document_family": document_family,
        "context_key": context_key,
        "primary_party_key": primary_party_key,
        "subject_key": subject_key,
        "period_key": period_key,
        "matter_key": None,
        "confidence": confidence,
        "evidence": {
            "document_type": document_type_code,
            "specialist_types": specialist_types,
            "entity_types": entity_types,
        },
    }

    # Only return if we have at least some signal
    filled_axes = sum(1 for k in [document_family, context_key, primary_party_key, subject_key, period_key] if k)
    if filled_axes == 0:
        return None

    return identity
