from __future__ import annotations

import re
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from common.db.models import DocumentUnit, DocumentUnitEntity, DocumentUnitLink


def process_utility_bill(
    db: Session,
    document_unit: DocumentUnit,
    segment_text: str,
    input_version: str,
) -> tuple[dict[str, Any], list[DocumentUnitLink], float]:
    text = segment_text or ""
    entity_map = _entity_values(document_unit.entities)

    issuer = _pick_first(
        _regex_group(text, r"(?:Eni gas e luce|Eni Plenitude|Enel(?: Servizio Elettrico)?|Acque S\.?p\.?A\.?|Toscana Energia|Publiacqua)[^\n]*"),
        entity_map.get("fornitore", []),
        entity_map.get("organizzazione", []),
    )
    account_holder = _pick_first(
        entity_map.get("persona", []),
        _extract_account_holder(text),
        entity_map.get("organizzazione", []),
    )
    issue_date = _extract_date_near(text, ["data di emissione"])
    due_date = _extract_due_date(text)
    total_amount = _extract_total_amount(text)
    document_number = _pick_first(
        _extract_code_near(text, ["rif.bolletta", "riferimento fattura", "rif. bolletta", "numero fattura"]),
        entity_map.get("numero_documento", []),
    )
    contract_code = _extract_code_near(text, ["numero contratto", "numerocontratto"])
    supply_code = _extract_code_near(text, ["pod", "pdr", "numero cliente"])
    billing_period = _extract_period(text)
    payment_status = _payment_status(text)
    service_type = _service_type(text)
    header_reference = _pick_first(
        _regex_group(text, r"La mia fornitura[^\n]*\n+([A-Z0-9 ,.'/()-]{8,})"),
        entity_map.get("indirizzo", []),
    )

    links: list[DocumentUnitLink] = []
    for target_unit, link_type, confidence, rationale in _find_related_candidates(
        db,
        document_unit,
        issuer,
        document_number,
        billing_period["from"],
        billing_period["to"],
    ):
        links.append(
            DocumentUnitLink(
                source_document_unit_id=document_unit.id,
                target_document_unit_id=target_unit.id,
                link_type=link_type,
                confidence=confidence,
                rationale=rationale,
            )
        )

    confidence = 0.0
    for field in [issuer, issue_date, due_date, total_amount, account_holder]:
        if field:
            confidence += 0.18
    if document_number:
        confidence += 0.08
    if billing_period["from"] or billing_period["to"]:
        confidence += 0.08
    if payment_status != "unknown":
        confidence += 0.06
    confidence = min(confidence, 0.98)

    result = {
        "document_kind": "utility_bill",
        "input_version": input_version,
        "issuer": issuer,
        "service_type": service_type,
        "account_holder": account_holder,
        "issue_date": issue_date,
        "due_date": due_date,
        "billing_period_from": billing_period["from"],
        "billing_period_to": billing_period["to"],
        "total_amount": total_amount,
        "currency": "EUR" if total_amount is not None else None,
        "document_number": document_number,
        "contract_code": contract_code,
        "pod_pdr_or_supply_code": supply_code,
        "supply_reference": header_reference,
        "payment_status": payment_status,
        "detail_link_candidates": [
            {
                "target_document_unit_id": str(link.target_document_unit_id),
                "confidence": link.confidence,
                "rationale": link.rationale,
            }
            for link in links
        ],
        "evidence": {
            "issuer_hint": issuer,
            "account_holder_hint": account_holder,
            "period_line_present": bool(billing_period["from"] or billing_period["to"]),
        },
    }
    return result, links, confidence


def _entity_values(entities: list[DocumentUnitEntity]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for entity in entities:
        values.setdefault(entity.entity_type, []).append(entity.entity_value)
    return values


def _pick_first(*values: Any) -> Any:
    for value in values:
        if isinstance(value, list):
            for item in value:
                if item:
                    return item.strip()
        elif value:
            return value.strip() if isinstance(value, str) else value
    return None


def _regex_group(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    if match.lastindex:
        return match.group(1).strip()
    return match.group(0).strip()


def _extract_date_near(text: str, anchors: list[str]) -> str | None:
    for anchor in anchors:
        pattern = rf"{re.escape(anchor)}[^\n\d]{{0,40}}(\d{{1,2}}[./-]\d{{1,2}}[./-]\d{{2,4}})"
        value = _regex_group(text, pattern)
        if value:
            return _normalize_date(value)
        fuzzy_pattern = rf"{re.escape(anchor)}[^\n\d]{{0,40}}(\d{{1,2}}\s+[A-Za-zà-ù]+(?:\s+\d{{2,4}})?)"
        fuzzy_value = _regex_group(text, fuzzy_pattern)
        if fuzzy_value:
            return _normalize_fuzzy_date(fuzzy_value)
    standalone = re.findall(r"\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b", text)
    if standalone:
        return _normalize_date(standalone[0])
    return None


def _normalize_date(value: str) -> str:
    parts = re.split(r"[./-]", value)
    if len(parts) != 3:
        return value
    day, month, year = parts
    if len(year) == 2:
        year = f"20{year}" if int(year) < 50 else f"19{year}"
    return f"{year.zfill(4)}-{month.zfill(2)}-{day.zfill(2)}"


def _extract_amount_near(text: str, anchors: list[str]) -> float | None:
    for anchor in anchors:
        pattern = rf"{re.escape(anchor)}[^\n\d-]{{0,50}}(-?\d{{1,3}}(?:\.\d{{3}})*(?:,\d{{2}})?)"
        value = _regex_group(text, pattern)
        parsed = _parse_amount(value)
        if parsed is not None:
            return parsed
    candidates = re.findall(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", text)
    amounts = [_parse_amount(candidate) for candidate in candidates]
    amounts = [amount for amount in amounts if amount is not None]
    return max(amounts) if amounts else None


def _extract_total_amount(text: str) -> float | None:
    strict_patterns = [
        r"Totale bolletta:?\s*(?:\n+\s*)?(-?\d{1,3}(?:\.\d{3})*(?:,\d{2})?)",
        r"Quanto devo pagare\??\s*(?:\n+\s*)?(-?\d{1,3}(?:\.\d{3})*(?:,\d{2})?)",
    ]
    for pattern in strict_patterns:
        value = _regex_group(text, pattern)
        parsed = _parse_amount(value)
        if parsed is not None:
            return parsed
    return _extract_amount_near(text, ["totale bolletta", "quanto devo pagare"])


def _parse_amount(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.replace(".", "").replace(",", ".").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_code_near(text: str, anchors: list[str]) -> str | None:
    for anchor in anchors:
        pattern = rf"{re.escape(anchor)}[^\nA-Z0-9]{{0,40}}([A-Z0-9][A-Z0-9 ./_-]{{4,40}})"
        value = _regex_group(text, pattern)
        if value:
            return re.sub(r"\s+", "", value)
    return None


def _extract_account_holder(text: str) -> str | None:
    patterns = [
        r"Contratto intestato a\s*([A-ZÀ-ÖØ-Ý' ]{6,})",
        r"eseguitoda:?\s*([A-ZÀ-ÖØ-Ý' ]{6,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        candidate = re.sub(r"\s+", " ", match.group(1)).strip()
        candidate = re.split(r"\s+\d{4,}|\s+VIA[A-Z ]+\d", candidate, maxsplit=1)[0].strip()
        if candidate and not candidate.lower().startswith("spa luce"):
            return candidate
    return None


def _extract_due_date(text: str) -> str | None:
    explicit_patterns = [
        r"Entro il\s+(\d{1,2}\s+[A-Za-zà-ù]+(?:\s+\d{2,4})?)",
        r"Scad\.?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
        r"Scadenza\s*(?:\n+\s*)?(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})",
    ]
    for pattern in explicit_patterns:
        value = _regex_group(text, pattern)
        if value:
            normalized = _normalize_fuzzy_date(value) if re.search(r"[A-Za-zà-ù]", value) else _normalize_date(value)
            if normalized:
                return normalized

    candidates = [
        _extract_date_near(text, ["entro quando devo pagare"]),
        _extract_date_near(text, ["entro il"]),
        _extract_date_near(text, ["scad"]),
    ]
    for candidate in candidates:
        if candidate:
            return candidate
    return None


def _extract_period(text: str) -> dict[str, str | None]:
    match = re.search(
        r"(?:periodo(?: di riferimento)?|consumo stimato\*\(dal)\s*(?:da\s*)?(\d{1,2}[ ./-][A-Za-zà-ù0-9]+(?:[ ./-]\d{2,4})?)\s*(?:a|al|-)\s*(\d{1,2}[ ./-][A-Za-zà-ù0-9]+(?:[ ./-]\d{2,4})?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return {"from": None, "to": None}
    return {
        "from": _normalize_fuzzy_date(match.group(1)),
        "to": _normalize_fuzzy_date(match.group(2)),
    }


def _normalize_fuzzy_date(value: str) -> str | None:
    month_map = {
        "gennaio": "01",
        "febbraio": "02",
        "marzo": "03",
        "aprile": "04",
        "maggio": "05",
        "giugno": "06",
        "luglio": "07",
        "agosto": "08",
        "settembre": "09",
        "ottobre": "10",
        "novembre": "11",
        "dicembre": "12",
        "gen": "01",
        "feb": "02",
        "mar": "03",
        "apr": "04",
        "mag": "05",
        "giu": "06",
        "lug": "07",
        "ago": "08",
        "set": "09",
        "ott": "10",
        "nov": "11",
        "dic": "12",
    }
    compact = value.lower().replace(".", " ").replace("/", " ").replace("-", " ")
    parts = [part for part in compact.split() if part]
    if len(parts) >= 3 and parts[1] in month_map:
        day = parts[0].zfill(2)
        month = month_map[parts[1]]
        year = parts[2]
        if len(year) == 2:
            year = f"20{year}" if int(year) < 50 else f"19{year}"
        return f"{year}-{month}-{day}"
    numeric = re.match(r"(\d{1,2})\s+(\d{1,2})\s+(\d{2,4})", compact)
    if numeric:
        day, month, year = numeric.groups()
        if len(year) == 2:
            year = f"20{year}" if int(year) < 50 else f"19{year}"
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return None


def _payment_status(text: str) -> str:
    lowered = text.lower()
    if "pagamenti delle bollette precedenti risultano regolari" in lowered:
        return "paid"
    if re.search(r"\bpagat[ao]\b", lowered):
        return "paid"
    if re.search(r"\binsolut[oa]\b|\bnon pagat[ao]\b|\bmoros", lowered):
        return "unpaid"
    return "unknown"


def _service_type(text: str) -> str:
    lowered = text.lower()
    if "gas" in lowered:
        return "gas"
    if "acqua" in lowered or "idrico" in lowered:
        return "water"
    if "energia elettrica" in lowered or "elettrica" in lowered or "pod" in lowered:
        return "electricity"
    if "telefono" in lowered or "telecom" in lowered:
        return "telecom"
    return "unknown"


def _find_related_candidates(
    db: Session,
    document_unit: DocumentUnit,
    issuer: str | None,
    document_number: str | None,
    period_from: str | None,
    period_to: str | None,
) -> list[tuple[DocumentUnit, str, float, str]]:
    if not issuer and not document_number:
        return []

    candidates = db.execute(
        select(DocumentUnit)
        .where(DocumentUnit.id != document_unit.id)
        .options(
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.scan_unit),
            selectinload(DocumentUnit.document_type),
        )
    ).scalars().all()

    matches: list[tuple[DocumentUnit, str, float, str]] = []
    issuer_tokens = set(re.findall(r"[a-z0-9]{3,}", (issuer or "").lower()))
    for candidate in candidates:
        haystack = " ".join(
            filter(
                None,
                [
                    candidate.title or "",
                    candidate.extracted_summary or "",
                    " ".join(entity.entity_value for entity in candidate.entities),
                ],
            )
        ).lower()
        candidate_type = candidate.document_type.code if candidate.document_type else None
        score = 0.0
        reasons: list[str] = []
        link_type = "utility_bill_reference"
        if document_number and document_number.lower() in haystack:
            score += 0.55
            reasons.append("same document number")
        if issuer_tokens and sum(token in haystack for token in issuer_tokens) >= max(1, len(issuer_tokens) // 2):
            score += 0.25
            reasons.append("same issuer")
        if period_from and period_from in haystack:
            score += 0.10
            reasons.append("same start period")
        if period_to and period_to in haystack:
            score += 0.10
            reasons.append("same end period")
        if re.search(r"\b(dettaglio|consumi|letture|componenti tariffarie|totale bolletta)\b", haystack):
            score += 0.12
            link_type = "utility_bill_detail"
            reasons.append("detail-like document")
        if re.search(r"\b(pagamento|quietanza|ricevuta|bonifico|estratto conto|mav|pagata)\b", haystack):
            score += 0.14
            link_type = "utility_bill_payment"
            reasons.append("payment-like document")
        if candidate_type in {"bolletta", "fattura"} and link_type == "utility_bill_reference":
            score += 0.05
        elif candidate_type in {"lettera", "nota"} and link_type == "utility_bill_reference":
            score += 0.03
        if score >= 0.45:
            matches.append((candidate, link_type, min(score, 0.95), ", ".join(reasons)))
    matches.sort(key=lambda item: item[2], reverse=True)
    return matches[:5]
