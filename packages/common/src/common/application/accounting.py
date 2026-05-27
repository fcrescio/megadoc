from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from common.db.models import (
    AccountingAccount,
    AccountingAccountAlias,
    AccountingFact,
    DocumentUnit,
    KnowledgeAssertion,
    KnowledgeContextMembership,
    KnowledgeNode,
    ScanUnit,
    SpecialistResult,
)


@dataclass
class AccountingProjectionStats:
    accounts: int
    facts: int


TOTAL_RECONCILIATION_TOLERANCE = Decimal("0.02")


def rebuild_accounting_facts(session: Session) -> AccountingProjectionStats:
    session.execute(delete(AccountingFact))
    session.execute(delete(AccountingAccountAlias))
    session.execute(delete(AccountingAccount))
    results = session.execute(
        select(SpecialistResult)
        .where(SpecialistResult.specialist_type == "accounting_statement")
        .options(selectinload(SpecialistResult.document_unit))
        .order_by(SpecialistResult.created_at.asc())
    ).scalars().all()
    for result in results:
        if result.document_unit is not None:
            project_accounting_result(session, result.document_unit, result, replace_existing=False)
    session.flush()
    return accounting_stats(session)


def project_accounting_result(
    session: Session,
    document_unit: DocumentUnit,
    specialist_result: SpecialistResult,
    *,
    replace_existing: bool = True,
) -> None:
    if specialist_result.specialist_type != "accounting_statement":
        return
    if replace_existing:
        session.execute(
            delete(AccountingFact).where(AccountingFact.specialist_result_id == specialist_result.id)
        )
        session.flush()

    scope_node, scope_key = _scope_for_document_unit(session, document_unit)
    accounts = specialist_result.result_json.get("accounts") if specialist_result.result_json else None
    if not isinstance(accounts, list):
        _remove_orphan_accounts(session)
        return

    for payload_account in accounts:
        if not isinstance(payload_account, dict):
            continue
        account_key = _safe_key(payload_account.get("account_key"))
        subject_label = _safe_text(payload_account.get("subject_label"))
        if account_key is None or subject_label is None:
            continue
        account = _get_or_create_account(
            session,
            scope_node=scope_node,
            scope_key=scope_key,
            account_key=account_key,
            unit_code=_safe_text(payload_account.get("unit_code"), limit=64),
            subject_label=subject_label,
        )
        aliases = payload_account.get("subject_aliases") or [subject_label]
        for alias in aliases:
            _ensure_account_alias(session, account, alias)
        facts = payload_account.get("facts")
        if not isinstance(facts, list):
            continue
        for payload_fact in facts:
            fact = _build_fact(document_unit, specialist_result, account, payload_fact)
            if fact is not None:
                session.add(fact)
    session.flush()
    _remove_orphan_accounts(session)


def accounting_stats(session: Session) -> AccountingProjectionStats:
    return AccountingProjectionStats(
        accounts=int(session.execute(select(func.count()).select_from(AccountingAccount)).scalar_one()),
        facts=int(session.execute(select(func.count()).select_from(AccountingFact)).scalar_one()),
    )


def find_context_account_subjects(
    session: Session,
    context_id: uuid.UUID | str,
    *,
    query: str | None = None,
    account_key: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    context_uuid = uuid.UUID(str(context_id))
    accounts = session.execute(
        select(AccountingAccount)
        .join(AccountingFact, AccountingFact.account_id == AccountingAccount.id)
        .join(
            KnowledgeContextMembership,
            KnowledgeContextMembership.document_unit_id == AccountingFact.document_unit_id,
        )
        .where(KnowledgeContextMembership.context_id == context_uuid)
        .options(selectinload(AccountingAccount.aliases))
    ).scalars().unique().all()
    grouped: dict[str, list[AccountingAccount]] = {}
    for account in accounts:
        grouped.setdefault(account.account_key, []).append(account)

    normalized_query = _normalize_key(query) if query and query.strip() else None
    normalized_account_key = _normalize_key(account_key) if account_key and account_key.strip() else None
    candidates: list[dict[str, Any]] = []
    for candidate_key, candidate_accounts in grouped.items():
        if normalized_account_key and candidate_key != normalized_account_key:
            continue
        aliases = sorted(
            {
                alias.alias
                for account in candidate_accounts
                for alias in account.aliases
            }
            | {account.subject_label for account in candidate_accounts}
        )
        searchable = {_normalize_key(value) for value in aliases}
        searchable.add(candidate_key)
        if normalized_query and not any(normalized_query in value for value in searchable):
            continue
        facts = _context_facts_for_accounts(
            session,
            context_uuid,
            [account.id for account in candidate_accounts],
        )
        periods = sorted(
            {
                (fact.accounting_role, fact.period_context_from, fact.period_context_to)
                for fact in facts
                if fact.accounting_role and fact.period_context_from and fact.period_context_to
            },
            key=lambda item: (item[1], item[2], item[0]),
        )
        candidates.append(
            {
                "account_key": candidate_key,
                "subject_label": candidate_accounts[0].subject_label,
                "aliases": aliases,
                "unit_codes": sorted({account.unit_code for account in candidate_accounts if account.unit_code}),
                "source_account_ids": [str(account.id) for account in candidate_accounts],
                "fact_count": len(facts),
                "available_periods": [
                    {
                        "accounting_role": role,
                        "period_from": period_from,
                        "period_to": period_to,
                    }
                    for role, period_from, period_to in periods
                ],
            }
        )
    return sorted(candidates, key=lambda item: (item["subject_label"].lower(), item["account_key"]))[:limit]


def compare_context_accounting_periods(
    session: Session,
    context_id: uuid.UUID | str,
    *,
    subject: str,
    period_a_from: date,
    period_a_to: date,
    period_b_from: date,
    period_b_to: date,
    accounting_role: str = "actual_allocation",
    account_key: str | None = None,
) -> dict[str, Any]:
    context_uuid = uuid.UUID(str(context_id))
    candidates = find_context_account_subjects(
        session,
        context_uuid,
        query=subject,
        account_key=account_key,
        limit=20,
    )
    response: dict[str, Any] = {
        "context_id": str(context_uuid),
        "requested_subject": subject,
        "accounting_role": accounting_role,
        "status": "subject_not_found",
        "warnings": [],
        "candidates": candidates,
        "selected_subject": None,
        "period_a": None,
        "period_b": None,
        "direction": None,
        "delta": None,
        "percentage_change": None,
        "changed_categories": [],
    }
    if not candidates:
        response["warnings"] = ["Nessun soggetto contabile corrispondente nel contesto selezionato."]
        return response
    if len(candidates) > 1:
        response["status"] = "ambiguous_subject"
        response["warnings"] = ["La ricerca identifica piu soggetti; specificare account_key prima del confronto."]
        return response

    candidate = candidates[0]
    facts = _context_facts_for_accounts(
        session,
        context_uuid,
        [uuid.UUID(account_id) for account_id in candidate["source_account_ids"]],
    )
    period_a = _period_breakdown(facts, accounting_role, period_a_from, period_a_to)
    period_b = _period_breakdown(facts, accounting_role, period_b_from, period_b_to)
    response["selected_subject"] = candidate
    response["period_a"] = period_a
    response["period_b"] = period_b

    if period_a["validation_status"] == "missing" or period_b["validation_status"] == "missing":
        response["status"] = "insufficient_data"
        response["warnings"] = [
            "Il confronto richiede lo stesso ruolo contabile in entrambi i periodi; almeno un periodo non e disponibile."
        ]
        if any(
            period["validation_status"] not in {"missing", "validated"}
            for period in (period_a, period_b)
        ):
            response["warnings"].append(
                "Almeno un periodo disponibile contiene voci il cui totale non e ancora riconciliato."
            )
        return response

    changes = _category_changes(period_a["categories"], period_b["categories"])
    response["changed_categories"] = changes
    invalid_periods = [
        item["validation_status"]
        for item in (period_a, period_b)
        if item["validation_status"] != "validated"
    ]
    if invalid_periods:
        response["status"] = "needs_review"
        response["warnings"] = [
            "Le voci sono disponibili ma almeno un totale non si riconcilia con le componenti estratte."
        ]
        return response

    total_a = Decimal(str(period_a["total"]))
    total_b = Decimal(str(period_b["total"]))
    delta = total_b - total_a
    response["status"] = "comparable"
    response["delta"] = float(delta)
    response["direction"] = "period_b_more" if delta > 0 else "period_b_less" if delta < 0 else "equal"
    response["percentage_change"] = (
        round(float((delta / total_a) * Decimal("100")), 2) if total_a != 0 else None
    )
    return response


def _context_facts_for_accounts(
    session: Session,
    context_id: uuid.UUID,
    account_ids: list[uuid.UUID],
) -> list[AccountingFact]:
    if not account_ids:
        return []
    return session.execute(
        select(AccountingFact)
        .join(
            KnowledgeContextMembership,
            KnowledgeContextMembership.document_unit_id == AccountingFact.document_unit_id,
        )
        .where(
            KnowledgeContextMembership.context_id == context_id,
            AccountingFact.account_id.in_(account_ids),
        )
        .options(
            selectinload(AccountingFact.document_unit)
            .selectinload(DocumentUnit.scan_unit)
            .selectinload(ScanUnit.document)
        )
    ).scalars().unique().all()


def _period_breakdown(
    facts: list[AccountingFact],
    accounting_role: str,
    period_from: date,
    period_to: date,
) -> dict[str, Any]:
    selected = [
        fact
        for fact in facts
        if fact.accounting_role == accounting_role
        and fact.period_context_from == period_from
        and fact.period_context_to == period_to
        and fact.fact_type == "allocated_expense"
    ]
    components = [fact for fact in selected if not fact.is_total and fact.category_key]
    totals = [fact for fact in selected if fact.is_total]
    categories: dict[str, dict[str, Any]] = {}
    for fact in components:
        item = categories.setdefault(
            fact.category_key or "unknown",
            {
                "category_key": fact.category_key or "unknown",
                "category_label": fact.category_label or fact.category_key or "Voce non identificata",
                "amount": Decimal("0.00"),
                "sources": [],
            },
        )
        item["amount"] += fact.amount
        document = fact.document_unit.scan_unit.document if fact.document_unit and fact.document_unit.scan_unit else None
        item["sources"].append(
            {
                "document_unit_id": str(fact.document_unit_id),
                "original_filename": document.original_filename if document else None,
                "start_page": fact.document_unit.start_page if fact.document_unit else None,
                "end_page": fact.document_unit.end_page if fact.document_unit else None,
                "evidence_json": fact.evidence_json,
            }
        )
    component_total = sum((item["amount"] for item in categories.values()), Decimal("0.00"))
    reported_total = totals[0].amount if len(totals) == 1 else None
    if not selected:
        validation_status = "missing"
    elif not components:
        validation_status = "missing_components"
    elif len(totals) != 1:
        validation_status = "ambiguous_total"
    elif abs(component_total - reported_total) <= TOTAL_RECONCILIATION_TOLERANCE:
        validation_status = "validated"
    else:
        validation_status = "inconsistent_total"
    return {
        "period_from": period_from,
        "period_to": period_to,
        "accounting_role": accounting_role,
        "validation_status": validation_status,
        "total": float(component_total) if components else None,
        "component_total": float(component_total) if components else None,
        "reported_total": float(reported_total) if reported_total is not None else None,
        "fact_count": len(selected),
        "categories": [
            {**item, "amount": float(item["amount"])}
            for item in sorted(categories.values(), key=lambda item: item["category_label"].lower())
        ],
    }


def _category_changes(period_a: list[dict[str, Any]], period_b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first = {item["category_key"]: item for item in period_a}
    second = {item["category_key"]: item for item in period_b}
    changes = []
    for key in set(first) | set(second):
        amount_a = Decimal(str(first.get(key, {}).get("amount", 0)))
        amount_b = Decimal(str(second.get(key, {}).get("amount", 0)))
        delta = amount_b - amount_a
        if delta == 0:
            continue
        changes.append(
            {
                "category_key": key,
                "category_label": (second.get(key) or first.get(key))["category_label"],
                "amount_a": float(amount_a),
                "amount_b": float(amount_b),
                "delta": float(delta),
                "percentage_change": (
                    round(float((delta / amount_a) * Decimal("100")), 2) if amount_a != 0 else None
                ),
                "sources_a": first.get(key, {}).get("sources", []),
                "sources_b": second.get(key, {}).get("sources", []),
            }
        )
    return sorted(changes, key=lambda item: abs(item["delta"]), reverse=True)


def _scope_for_document_unit(
    session: Session,
    document_unit: DocumentUnit,
) -> tuple[KnowledgeNode | None, str]:
    scope_node = session.execute(
        select(KnowledgeNode)
        .join(KnowledgeAssertion, KnowledgeAssertion.object_node_id == KnowledgeNode.id)
        .where(
            KnowledgeAssertion.document_unit_id == document_unit.id,
            KnowledgeAssertion.predicate_code == "about",
        )
        .order_by(KnowledgeAssertion.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    if scope_node is None:
        return None, f"document_unit:{document_unit.id}"
    return scope_node, f"{scope_node.node_kind}:{scope_node.canonical_key}"


def _get_or_create_account(
    session: Session,
    *,
    scope_node: KnowledgeNode | None,
    scope_key: str,
    account_key: str,
    unit_code: str | None,
    subject_label: str,
) -> AccountingAccount:
    account = session.execute(
        select(AccountingAccount).where(
            AccountingAccount.scope_key == scope_key,
            AccountingAccount.account_key == account_key,
        )
    ).scalar_one_or_none()
    if account is None:
        account = AccountingAccount(
            scope_node=scope_node,
            scope_key=scope_key,
            account_key=account_key,
            unit_code=unit_code,
            subject_label=subject_label,
            review_status="auto",
        )
        session.add(account)
        session.flush()
    _ensure_account_alias(session, account, subject_label)
    return account


def _ensure_account_alias(session: Session, account: AccountingAccount, value: Any) -> None:
    alias = _safe_text(value)
    if alias is None:
        return
    normalized_alias = _normalize_key(alias)
    if not any(item.normalized_alias == normalized_alias for item in account.aliases):
        account.aliases.append(
            AccountingAccountAlias(
                alias=alias,
                normalized_alias=normalized_alias,
            )
        )


def _build_fact(
    document_unit: DocumentUnit,
    specialist_result: SpecialistResult,
    account: AccountingAccount,
    payload: Any,
) -> AccountingFact | None:
    if not isinstance(payload, dict):
        return None
    fact_type = _safe_text(payload.get("fact_type"), limit=64)
    amount = _decimal_amount(payload.get("amount"))
    raw_amount = _decimal_amount(payload.get("raw_amount"))
    if fact_type is None or amount is None or raw_amount is None:
        return None
    context = payload.get("period_context") if isinstance(payload.get("period_context"), dict) else {}
    return AccountingFact(
        document_unit_id=document_unit.id,
        specialist_result_id=specialist_result.id,
        account_id=account.id,
        accounting_role=_safe_text(payload.get("accounting_role"), limit=64),
        fact_type=fact_type,
        category_key=_safe_key(payload.get("category_key")),
        category_label=_safe_text(payload.get("category_label")),
        amount=amount,
        raw_amount=raw_amount,
        currency=_safe_text(payload.get("currency"), limit=3) or "EUR",
        period_context_from=_date_value(context.get("from")),
        period_context_to=_date_value(context.get("to")),
        period_source=_safe_text(context.get("source"), limit=32),
        period_review_status=_safe_text(context.get("review_status"), limit=32),
        is_total=bool(payload.get("is_total", False)),
        confidence=specialist_result.confidence,
        review_status="auto",
        evidence_json=payload.get("evidence") if isinstance(payload.get("evidence"), dict) else None,
    )


def _remove_orphan_accounts(session: Session) -> None:
    session.flush()
    session.execute(
        delete(AccountingAccount).where(
            ~AccountingAccount.facts.any()
        )
    )


def _decimal_amount(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _date_value(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _safe_key(value: Any) -> str | None:
    text = _safe_text(value)
    return _normalize_key(text) if text else None


def _safe_text(value: Any, *, limit: int = 512) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).strip())
    if not text or len(text) > limit:
        return None
    return text


def _normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip().lower())
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_value).strip("_")[:512] or "unknown"
