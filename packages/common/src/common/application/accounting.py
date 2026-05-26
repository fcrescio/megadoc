from __future__ import annotations

import re
import unicodedata
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
    KnowledgeNode,
    SpecialistResult,
)


@dataclass
class AccountingProjectionStats:
    accounts: int
    facts: int


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
