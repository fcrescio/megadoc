import uuid
from datetime import date
from decimal import Decimal

from api.routers.knowledge import compare_context_accounting, list_context_accounting_subjects
from common.application.accounting import compare_context_accounting_periods, find_context_account_subjects
from common.db.models import (
    AccountingAccount,
    AccountingAccountAlias,
    AccountingFact,
    CanonicalEntity,
    Document,
    DocumentUnit,
    KnowledgeContext,
    KnowledgeContextMembership,
    ScanUnit,
)


def _make_context_comparison(db_session) -> KnowledgeContext:
    canonical = CanonicalEntity(
        entity_type="organizzazione",
        canonical_value="condominio_via_roma",
        display_value="Condominio Via Roma",
        review_status="human_reviewed",
    )
    context = KnowledgeContext(
        context_kind="entity",
        canonical_entity=canonical,
        label=canonical.display_value,
        review_status="human_reviewed",
    )
    for index, (filename, period_from, period_to, components, reported_total) in enumerate(
        [
            (
                "rendiconto-2022-2023.pdf",
                date(2022, 7, 1),
                date(2023, 6, 30),
                {"spese_generali": ("Spese generali", Decimal("60.00")), "ascensore": ("Ascensore", Decimal("40.00"))},
                Decimal("100.00"),
            ),
            (
                "rendiconto-2023-2024.pdf",
                date(2023, 7, 1),
                date(2024, 6, 30),
                {"spese_generali": ("Spese generali", Decimal("90.00")), "ascensore": ("Ascensore", Decimal("40.00"))},
                Decimal("130.00"),
            ),
        ],
        start=1,
    ):
        document = Document(
            original_filename=filename,
            mime_type="application/pdf",
            sha256=str(index) * 64,
            size_bytes=100,
            source_type="upload",
        )
        scan_unit = ScanUnit(
            document=document,
            source_document_id=document.id,
            source_ocr_result_id=uuid.uuid4(),
            page_count=1,
            status="assigned",
        )
        unit = DocumentUnit(
            scan_unit=scan_unit,
            ordinal=1,
            start_page=1,
            end_page=1,
            review_status="auto_accepted",
        )
        context.memberships.append(
            KnowledgeContextMembership(
                document_unit=unit,
                membership_role="direct",
                confidence=0.95,
                source_type="canonical_entity",
            )
        )
        account = AccountingAccount(
            scope_key=f"scope:{index}",
            account_key="b11",
            unit_code="B11",
            subject_label="BONACCI FABIO",
            review_status="auto",
        )
        account.aliases.append(AccountingAccountAlias(alias="Fabio Bonacci", normalized_alias="fabio_bonacci"))
        for key, (label, amount) in components.items():
            account.facts.append(
                AccountingFact(
                    document_unit=unit,
                    accounting_role="actual_allocation",
                    fact_type="allocated_expense",
                    category_key=key,
                    category_label=label,
                    amount=amount,
                    raw_amount=amount,
                    currency="EUR",
                    period_context_from=period_from,
                    period_context_to=period_to,
                    is_total=False,
                    evidence_json={"row": key},
                    review_status="auto",
                )
            )
        account.facts.append(
            AccountingFact(
                document_unit=unit,
                accounting_role="actual_allocation",
                fact_type="allocated_expense",
                category_key="totale_gestione",
                category_label="Totale gestione",
                amount=reported_total,
                raw_amount=reported_total,
                currency="EUR",
                period_context_from=period_from,
                period_context_to=period_to,
                is_total=True,
                review_status="auto",
            )
        )
        db_session.add_all([document, scan_unit, unit, account])
    db_session.add_all([canonical, context])
    db_session.flush()
    return context


def _compare(db_session, context_id):
    return compare_context_accounting_periods(
        db_session,
        context_id,
        subject="Bonacci",
        period_a_from=date(2022, 7, 1),
        period_a_to=date(2023, 6, 30),
        period_b_from=date(2023, 7, 1),
        period_b_to=date(2024, 6, 30),
    )


def test_comparison_merges_account_scopes_and_explains_category_delta(db_session):
    context = _make_context_comparison(db_session)

    subjects = find_context_account_subjects(db_session, context.id, query="Bonacci")
    result = _compare(db_session, context.id)

    assert len(subjects) == 1
    assert len(subjects[0]["source_account_ids"]) == 2
    assert result["status"] == "comparable"
    assert result["direction"] == "period_b_more"
    assert result["delta"] == 30.0
    assert result["percentage_change"] == 30.0
    assert result["changed_categories"][0]["category_label"] == "Spese generali"
    assert result["changed_categories"][0]["sources_b"][0]["original_filename"] == "rendiconto-2023-2024.pdf"


def test_comparison_requires_reconciled_totals(db_session):
    context = _make_context_comparison(db_session)
    fact = (
        db_session.query(AccountingFact)
        .filter(
            AccountingFact.is_total.is_(True),
            AccountingFact.period_context_from == date(2023, 7, 1),
        )
        .one()
    )
    fact.amount = Decimal("999.00")

    result = _compare(db_session, context.id)

    assert result["status"] == "needs_review"
    assert result["period_b"]["validation_status"] == "inconsistent_total"
    assert result["direction"] is None


def test_accounting_comparison_api_exposes_subjects_and_insufficient_data(db_session):
    context = _make_context_comparison(db_session)

    subjects = list_context_accounting_subjects(context.id, q="Bonacci", account_key=None, limit=20, db=db_session)
    result = compare_context_accounting(
        context.id,
        subject="Bonacci",
        period_a_from=date(2022, 7, 1),
        period_a_to=date(2023, 6, 30),
        period_b_from=date(2024, 7, 1),
        period_b_to=date(2025, 6, 30),
        accounting_role="actual_allocation",
        account_key=None,
        db=db_session,
    )

    assert subjects[0]["account_key"] == "b11"
    assert result["status"] == "insufficient_data"
    assert result["period_b"]["validation_status"] == "missing"
