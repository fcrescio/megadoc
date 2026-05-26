import uuid
from decimal import Decimal

from common.application.accounting import accounting_stats, project_accounting_result, rebuild_accounting_facts
from common.application.graph import project_document_unit
from common.db.models import (
    AccountingAccount,
    AccountingFact,
    Document,
    DocumentType,
    DocumentUnit,
    DocumentUnitEntity,
    ScanUnit,
    SpecialistResult,
)


def _make_statement_unit(db_session) -> tuple[DocumentUnit, SpecialistResult]:
    document = Document(
        original_filename="rendiconto.pdf",
        mime_type="application/pdf",
        sha256="c" * 64,
        size_bytes=100,
        source_type="upload",
    )
    doc_type = DocumentType(code="rendiconto_contabile", name="Rendiconto", is_active=True)
    scan_unit = ScanUnit(
        document=document,
        source_document_id=document.id,
        source_ocr_result_id=uuid.uuid4(),
        page_count=2,
        status="assigned",
    )
    unit = DocumentUnit(
        scan_unit=scan_unit,
        document_type=doc_type,
        document_type_confidence=0.96,
        ordinal=1,
        start_page=1,
        end_page=2,
        review_status="auto_accepted",
    )
    unit.entities.append(
        DocumentUnitEntity(
            entity_type="organizzazione",
            entity_value="Condominio Via Roma",
            normalized_value="condominio_via_roma",
            confidence=0.94,
            page_from=1,
            page_to=1,
        )
    )
    result = SpecialistResult(
        document_unit=unit,
        specialist_type="accounting_statement",
        schema_version="accounting_statement_v3",
        confidence=0.93,
        review_status="auto_accepted",
        result_json={
            "accounts": [
                {
                    "account_key": "b11",
                    "unit_code": "B11",
                    "subject_label": "BONACCI FABIO",
                    "subject_aliases": ["BONACCI FABIO", "Fabio Bonacci"],
                    "facts": [
                        {
                            "fact_type": "allocated_expense",
                            "accounting_role": "actual_allocation",
                            "category_key": "spese_generali",
                            "category_label": "Spese generali",
                            "amount": 362.59,
                            "raw_amount": -362.59,
                            "currency": "EUR",
                            "period_context": {
                                "from": "2022-07-01",
                                "to": "2023-06-30",
                                "source": "document_unit",
                                "review_status": "unverified",
                            },
                            "is_total": False,
                            "evidence": {"table_id": "riparto", "row_id": "row_11", "column": "Spese generali"},
                        }
                    ],
                }
            ]
        },
    )
    db_session.add_all([document, doc_type, scan_unit, unit, result])
    db_session.flush()
    return unit, result


def test_accounting_projection_materializes_scoped_facts(db_session):
    unit, result = _make_statement_unit(db_session)
    project_document_unit(db_session, unit)

    project_accounting_result(db_session, unit, result)
    db_session.flush()

    account = db_session.query(AccountingAccount).one()
    fact = db_session.query(AccountingFact).one()
    assert account.scope_key == "organization:condominio_via_roma"
    assert account.unit_code == "B11"
    assert {alias.alias for alias in account.aliases} == {"BONACCI FABIO", "Fabio Bonacci"}
    assert fact.fact_type == "allocated_expense"
    assert fact.accounting_role == "actual_allocation"
    assert fact.amount == Decimal("362.59")
    assert fact.raw_amount == Decimal("-362.59")
    assert fact.period_source == "document_unit"
    assert fact.period_review_status == "unverified"
    assert fact.evidence_json["row_id"] == "row_11"


def test_accounting_projection_is_rebuildable_and_idempotent(db_session):
    unit, result = _make_statement_unit(db_session)
    project_document_unit(db_session, unit)
    project_accounting_result(db_session, unit, result)
    project_accounting_result(db_session, unit, result)

    first = accounting_stats(db_session)
    rebuilt = rebuild_accounting_facts(db_session)

    assert first.accounts == rebuilt.accounts == 1
    assert first.facts == rebuilt.facts == 1
