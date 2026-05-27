import copy
import uuid
from decimal import Decimal

from common.application.accounting import (
    accounting_stats,
    apply_manual_accounting_correction,
    project_accounting_result,
    reapply_manual_accounting_corrections,
    rebuild_accounting_facts,
)
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
        schema_version="accounting_statement_v5",
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


def test_manual_accounting_correction_is_audited_and_reprojected(db_session):
    unit, result = _make_statement_unit(db_session)
    project_document_unit(db_session, unit)
    project_accounting_result(db_session, unit, result)
    db_session.flush()
    source_fact = db_session.query(AccountingFact).one()

    response = apply_manual_accounting_correction(
        db_session,
        source_fact.id,
        corrected_amount=Decimal("400.00"),
        corrected_category_label="Spese generali corrette",
        note="Verificato sulla tabella originale.",
        acted_by="revisore",
    )

    corrected_fact = db_session.query(AccountingFact).one()
    assert response["review_status"] == "human_reviewed"
    assert corrected_fact.amount == Decimal("400.00")
    assert corrected_fact.raw_amount == Decimal("-362.59")
    assert corrected_fact.category_key == "spese_generali_corrette"
    assert corrected_fact.review_status == "human_reviewed"
    assert result.result_json["manual_corrections"][0]["acted_by"] == "revisore"
    assert result.result_json["manual_corrections"][0]["before"]["amount"] == 362.59

    rebuild_accounting_facts(db_session)
    rebuilt_fact = db_session.query(AccountingFact).one()
    assert rebuilt_fact.amount == Decimal("400.00")
    assert rebuilt_fact.category_label == "Spese generali corrette"


def test_manual_accounting_correction_is_reapplied_after_specialist_reprocessing(db_session):
    unit, result = _make_statement_unit(db_session)
    project_document_unit(db_session, unit)
    project_accounting_result(db_session, unit, result)
    db_session.flush()
    source_fact = db_session.query(AccountingFact).one()
    generated_payload = copy.deepcopy(result.result_json)

    apply_manual_accounting_correction(
        db_session,
        source_fact.id,
        corrected_amount=Decimal("400.00"),
        acted_by="revisore",
    )

    reapplied = reapply_manual_accounting_corrections(generated_payload, result.result_json)

    fact = reapplied["accounts"][0]["facts"][0]
    assert fact["amount"] == 400.0
    assert fact["review_status"] == "human_reviewed"
    assert reapplied["manual_corrections"][0]["application_status"] == "reapplied"
