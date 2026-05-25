from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from common.db.models import (
    CanonicalEntity,
    CanonicalEntityVariant,
    DocumentUnit,
    DocumentUnitEntity,
    DocumentUnitMention,
    KnowledgeAssertion,
    KnowledgeNode,
    KnowledgeNodeAlias,
    KnowledgePredicate,
    SpecialistResult,
)


PREDICATE_REGISTRY: dict[str, tuple[str, str, str]] = {
    "about": ("Riguarda", "node", "Oggetto, immobile o pratica a cui il documento si riferisce."),
    "document_type": ("Tipo documento", "text", "Tipo archivistico o specialistico del segmento."),
    "issued_by": ("Emesso da", "node", "Organizzazione che ha emesso il documento."),
    "addressed_to": ("Destinatario", "node", "Persona o organizzazione destinataria."),
    "service_type": ("Servizio", "text", "Tipo di utenza o servizio."),
    "issue_date": ("Data emissione", "date", "Data di emissione del documento."),
    "due_date": ("Scadenza", "date", "Data entro la quale e' richiesto un adempimento."),
    "covers_period": ("Periodo", "period", "Intervallo temporale coperto dal documento."),
    "amount_total": ("Importo totale", "money", "Importo totale estratto dal documento."),
    "payment_status": ("Stato pagamento", "status", "Stato del pagamento dedotto dal documento."),
    "document_number": ("Numero documento", "text", "Identificatore dichiarato del documento."),
    "contract_code": ("Codice contratto", "text", "Identificatore del contratto."),
    "supply_code": ("Codice fornitura", "text", "Identificatore dell'utenza o fornitura."),
    "statement_type": ("Tipo rendiconto", "text", "Tipo di prospetto contabile."),
    "validation_status": ("Verifica contabile", "status", "Esito aggregato dei controlli numerici."),
}

ENTITY_KIND_MAP = {
    "persona": "person",
    "organizzazione": "organization",
    "indirizzo": "address",
    "luogo": "place",
}

MAX_NODE_TEXT_LENGTH = 512
MAX_ASSERTION_TEXT_LENGTH = 1024
TABLE_MARKUP_PATTERN = re.compile(r"</?(?:table|tbody|thead|tr|td|th)\b", re.IGNORECASE)


@dataclass
class GraphProjectionStats:
    document_units: int
    nodes: int
    mentions: int
    assertions: int


def ensure_predicate_registry(session: Session) -> None:
    existing = set(session.execute(select(KnowledgePredicate.code)).scalars().all())
    for code, (label, value_kind, description) in PREDICATE_REGISTRY.items():
        if code in existing:
            continue
        session.add(
            KnowledgePredicate(
                code=code,
                label=label,
                value_kind=value_kind,
                description=description,
                is_facetable=True,
                is_active=True,
            )
        )
    session.flush()


def rebuild_knowledge_graph(session: Session) -> GraphProjectionStats:
    session.execute(delete(KnowledgeAssertion))
    session.execute(delete(DocumentUnitMention))
    session.execute(delete(KnowledgeNodeAlias))
    session.execute(delete(KnowledgeNode))
    ensure_predicate_registry(session)

    document_units = session.execute(
        select(DocumentUnit)
        .options(
            selectinload(DocumentUnit.entities),
            selectinload(DocumentUnit.document_type),
            selectinload(DocumentUnit.specialist_results),
        )
        .order_by(DocumentUnit.created_at.asc())
    ).scalars().all()
    for document_unit in document_units:
        project_document_unit(session, document_unit, replace_existing=False)
    session.flush()
    return graph_stats(session)


def project_document_unit(
    session: Session,
    document_unit: DocumentUnit,
    *,
    replace_existing: bool = True,
) -> None:
    ensure_predicate_registry(session)
    if replace_existing:
        session.execute(
            delete(KnowledgeAssertion).where(KnowledgeAssertion.document_unit_id == document_unit.id)
        )
        session.execute(
            delete(DocumentUnitMention).where(DocumentUnitMention.document_unit_id == document_unit.id)
        )
        session.flush()

    latest_results: dict[str, SpecialistResult] = {}
    for result in sorted(document_unit.specialist_results, key=lambda item: item.created_at, reverse=True):
        latest_results.setdefault(result.specialist_type, result)

    mentioned_nodes: dict[str, list[KnowledgeNode]] = {}
    for entity in document_unit.entities:
        node_kind = ENTITY_KIND_MAP.get(entity.entity_type)
        if node_kind is None:
            continue
        if node_kind == "person" and "accounting_statement" in latest_results:
            continue
        surface_text = _navigable_label(entity.entity_value)
        if surface_text is None:
            continue
        label, canonical_key = _entity_node_identity(session, entity)
        node = _get_or_create_node(
            session,
            node_kind=node_kind,
            label=label,
            canonical_key=canonical_key,
        )
        _ensure_alias(session, node, surface_text)
        mentioned_nodes.setdefault(node_kind, []).append(node)
        session.add(
            DocumentUnitMention(
                document_unit_id=document_unit.id,
                node_id=node.id,
                mention_role="mentioned",
                source_type="entity",
                surface_text=surface_text,
                confidence=entity.confidence,
                page_from=entity.page_from,
                page_to=entity.page_to,
                evidence_json={"entity_type": entity.entity_type},
            )
        )

    source_confidence = document_unit.document_type_confidence
    if document_unit.document_type is not None:
        _add_value_assertion(
            session,
            document_unit,
            "document_type",
            document_unit.document_type.code,
            source_type="classification",
            confidence=source_confidence,
        )

    about_node = _select_about_node(mentioned_nodes)
    if about_node is not None:
        _add_node_assertion(
            session,
            document_unit,
            "about",
            about_node,
            source_type="entity",
            confidence=source_confidence,
        )

    utility_result = latest_results.get("utility_bill")
    if utility_result is not None:
        _project_utility_bill(session, document_unit, utility_result, about_node)

    accounting_result = latest_results.get("accounting_statement")
    if accounting_result is not None:
        _project_accounting_statement(session, document_unit, accounting_result)

    session.flush()


def graph_stats(session: Session) -> GraphProjectionStats:
    return GraphProjectionStats(
        document_units=int(session.execute(select(func.count()).select_from(DocumentUnit)).scalar_one()),
        nodes=int(session.execute(select(func.count()).select_from(KnowledgeNode)).scalar_one()),
        mentions=int(session.execute(select(func.count()).select_from(DocumentUnitMention)).scalar_one()),
        assertions=int(session.execute(select(func.count()).select_from(KnowledgeAssertion)).scalar_one()),
    )


def _project_utility_bill(
    session: Session,
    document_unit: DocumentUnit,
    result: SpecialistResult,
    about_node: KnowledgeNode | None,
) -> None:
    payload = result.result_json or {}
    confidence = result.confidence
    raw_issuer = payload.get("issuer")
    issuer = _navigable_label(raw_issuer)
    issuer_supplied = raw_issuer is not None and str(raw_issuer).strip().lower() not in {"", "unknown"}
    if issuer_supplied and issuer is None:
        return

    _add_value_assertion(session, document_unit, "document_type", "utility_bill", result, confidence)
    if issuer is not None:
        issuer_node = _get_or_create_node(session, node_kind="organization", label=issuer)
        _add_node_assertion(session, document_unit, "issued_by", issuer_node, result, confidence)

    holder = _navigable_label(payload.get("account_holder"))
    if holder is not None:
        holder_kind = "organization" if "condominio" in holder.lower() else "person"
        holder_node = _get_or_create_node(session, node_kind=holder_kind, label=holder)
        _add_node_assertion(session, document_unit, "addressed_to", holder_node, result, confidence)

    supply_reference = _navigable_label(payload.get("supply_reference"))
    if about_node is None and supply_reference is not None:
        reference_node = _get_or_create_node(
            session, node_kind="address", label=supply_reference
        )
        _add_node_assertion(session, document_unit, "about", reference_node, result, confidence)

    scalar_mapping = {
        "service_type": "service_type",
        "issue_date": "issue_date",
        "due_date": "due_date",
        "payment_status": "payment_status",
        "document_number": "document_number",
        "contract_code": "contract_code",
        "pod_pdr_or_supply_code": "supply_code",
    }
    for payload_key, predicate in scalar_mapping.items():
        value = payload.get(payload_key)
        if value not in {None, "", "unknown"}:
            _add_value_assertion(session, document_unit, predicate, value, result, confidence)

    period_from = payload.get("billing_period_from")
    period_to = payload.get("billing_period_to")
    if period_from or period_to:
        _add_value_assertion(
            session,
            document_unit,
            "covers_period",
            {"from": period_from, "to": period_to},
            result,
            confidence,
        )
    if payload.get("total_amount") is not None:
        _add_value_assertion(
            session,
            document_unit,
            "amount_total",
            {"amount": payload["total_amount"], "currency": payload.get("currency")},
            result,
            confidence,
        )


def _project_accounting_statement(
    session: Session,
    document_unit: DocumentUnit,
    result: SpecialistResult,
) -> None:
    payload = result.result_json or {}
    confidence = result.confidence
    _add_value_assertion(session, document_unit, "document_type", "accounting_statement", result, confidence)
    statement_type = payload.get("statement_type")
    if statement_type not in {None, "", "unknown"}:
        _add_value_assertion(session, document_unit, "statement_type", statement_type, result, confidence)
    period_from = payload.get("accounting_period_from")
    period_to = payload.get("accounting_period_to")
    if period_from or period_to:
        _add_value_assertion(
            session,
            document_unit,
            "covers_period",
            {"from": period_from, "to": period_to},
            result,
            confidence,
        )
    checks = payload.get("validation_checks") or []
    statuses = [
        check.get("status")
        for check in checks
        if isinstance(check, dict) and check.get("status")
    ]
    if statuses:
        status = "fail" if "fail" in statuses else "pass" if "pass" in statuses else "unknown"
        _add_value_assertion(session, document_unit, "validation_status", status, result, confidence)


def _get_or_create_node(
    session: Session,
    *,
    node_kind: str,
    label: str,
    canonical_key: str | None = None,
) -> KnowledgeNode:
    safe_label = _bounded_text(label, MAX_NODE_TEXT_LENGTH) or "unknown"
    normalized_key = _normalize_key(canonical_key or safe_label)
    node = session.execute(
        select(KnowledgeNode).where(
            KnowledgeNode.node_kind == node_kind,
            KnowledgeNode.canonical_key == normalized_key,
        )
    ).scalar_one_or_none()
    if node is None:
        node = KnowledgeNode(
            node_kind=node_kind,
            canonical_key=normalized_key,
            label=safe_label,
            review_status="auto",
        )
        session.add(node)
        session.flush()
    _ensure_alias(session, node, safe_label)
    return node


def _entity_node_identity(session: Session, entity: DocumentUnitEntity) -> tuple[str, str]:
    entity_key = (entity.normalized_value or entity.entity_value).strip().lower()
    canonical = session.execute(
        select(CanonicalEntity)
        .join(CanonicalEntityVariant, CanonicalEntityVariant.canonical_entity_id == CanonicalEntity.id)
        .where(
            CanonicalEntityVariant.entity_type == entity.entity_type,
            CanonicalEntityVariant.entity_key == entity_key,
        )
    ).scalar_one_or_none()
    if canonical is not None:
        return canonical.display_value, canonical.canonical_value
    return entity.entity_value, entity.entity_value


def _ensure_alias(session: Session, node: KnowledgeNode, alias: str) -> None:
    safe_alias = _bounded_text(alias, MAX_NODE_TEXT_LENGTH)
    if not safe_alias:
        return
    normalized_alias = _normalize_key(safe_alias)
    if any(item.normalized_alias == normalized_alias for item in node.aliases):
        return
    existing = session.execute(
        select(KnowledgeNodeAlias).where(
            KnowledgeNodeAlias.node_id == node.id,
            KnowledgeNodeAlias.normalized_alias == normalized_alias,
        )
    ).scalar_one_or_none()
    if existing is None:
        node.aliases.append(
            KnowledgeNodeAlias(
                alias=safe_alias,
                normalized_alias=normalized_alias,
            )
        )


def _select_about_node(mentioned_nodes: dict[str, list[KnowledgeNode]]) -> KnowledgeNode | None:
    organizations = mentioned_nodes.get("organization", [])
    for node in organizations:
        if "condominio" in node.label.lower() and node.canonical_key != "condominio":
            return node
    for kind in ("address", "organization", "place"):
        nodes = mentioned_nodes.get(kind, [])
        if nodes:
            return nodes[0]
    return None


def _add_node_assertion(
    session: Session,
    document_unit: DocumentUnit,
    predicate_code: str,
    object_node: KnowledgeNode,
    specialist_result: SpecialistResult | None = None,
    confidence: float | None = None,
    *,
    source_type: str | None = None,
) -> None:
    session.add(
        KnowledgeAssertion(
            document_unit_id=document_unit.id,
            predicate_code=predicate_code,
            object_node_id=object_node.id,
            confidence=confidence,
            review_status="auto",
            source_type=source_type or (specialist_result.specialist_type if specialist_result else "entity"),
            specialist_result_id=specialist_result.id if specialist_result else None,
        )
    )


def _add_value_assertion(
    session: Session,
    document_unit: DocumentUnit,
    predicate_code: str,
    value: Any,
    specialist_result: SpecialistResult | None = None,
    confidence: float | None = None,
    *,
    source_type: str | None = None,
) -> None:
    text_value = _navigable_assertion_text(value)
    if text_value is None:
        return
    session.add(
        KnowledgeAssertion(
            document_unit_id=document_unit.id,
            predicate_code=predicate_code,
            value_json=value,
            value_text=text_value,
            confidence=confidence,
            review_status="auto",
            source_type=source_type or (specialist_result.specialist_type if specialist_result else "classification"),
            specialist_result_id=specialist_result.id if specialist_result else None,
        )
    )


def _display_value(value: Any) -> str:
    if isinstance(value, dict):
        if "amount" in value:
            return f"{value['amount']} {value.get('currency') or ''}".strip()
        return " - ".join(str(item) for item in (value.get("from"), value.get("to")) if item)
    return str(value)


def _navigable_label(value: Any) -> str | None:
    if value is None:
        return None
    text = _bounded_text(str(value), MAX_NODE_TEXT_LENGTH, reject_oversized=True)
    if not text or TABLE_MARKUP_PATTERN.search(text):
        return None
    return text


def _navigable_assertion_text(value: Any) -> str | None:
    text = _bounded_text(_display_value(value), MAX_ASSERTION_TEXT_LENGTH, reject_oversized=True)
    if not text or TABLE_MARKUP_PATTERN.search(text):
        return None
    return text


def _bounded_text(value: str, limit: int, *, reject_oversized: bool = False) -> str | None:
    text = re.sub(r"\s+", " ", value.strip())
    if not text:
        return None
    if len(text) > limit:
        return None if reject_oversized else text[:limit]
    return text


def _normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = re.sub(r"\bs[\W_]*p[\W_]*a\b", "spa", ascii_value)
    ascii_value = re.sub(r"\bs[\W_]*r[\W_]*l\b", "srl", ascii_value)
    ascii_value = re.sub(r"\bs[\W_]*n[\W_]*c\b", "snc", ascii_value)
    return re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")[:512] or "unknown"
