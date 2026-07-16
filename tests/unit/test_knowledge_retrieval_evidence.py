from api.routers import knowledge
from api.routers.knowledge import (
    _KnowledgeAgentAction,
    _run_knowledge_agent_tool,
    _specialist_search_evidence,
)
from common.db.models import DocumentUnit, SpecialistResult


def test_agent_action_accepts_unified_evidence_retrieval():
    action = _KnowledgeAgentAction.model_validate(
        {
            "action": "retrieve_evidence",
            "query": "spese ascensore Crescioli",
            "document_id": "a61e4d32-9ce8-46bc-8bdf-f29c49285497",
            "limit": 6,
        }
    )

    assert action.action == "retrieve_evidence"
    assert action.query == "spese ascensore Crescioli"
    assert action.limit == 6


def test_accounting_evidence_uses_llm_explanation_and_table_page():
    unit = DocumentUnit(start_page=4, end_page=12, ordinal=1, review_status="auto_accepted")
    result = SpecialistResult(
        specialist_type="accounting_statement",
        schema_version="accounting_v1",
        review_status="auto_accepted",
        result_json={
            "accounting_period_from": "2023-01-01",
            "accounting_period_to": "2023-12-31",
            "tables": [
                {
                    "table_id": "table_7",
                    "table_type": "allocation",
                    "page_number": 9,
                    "headers": ["Unita", "Ascensore", "Acqua"],
                    "llm_explanation": {
                        "summary": "Ripartizione preventiva per unita immobiliare.",
                        "source": "accounting_reconciliation_llm",
                    },
                }
            ],
        },
    )

    evidence = _specialist_search_evidence(result, unit)

    assert len(evidence) == 1
    assert evidence[0]["page_from"] == 9
    assert evidence[0]["page_to"] == 9
    assert "Ripartizione preventiva" in evidence[0]["text"]
    assert "Colonne: Unita, Ascensore, Acqua" in evidence[0]["text"]
    assert evidence[0]["metadata"]["table_id"] == "table_7"


def test_utility_evidence_contains_payable_fields():
    unit = DocumentUnit(start_page=2, end_page=3, ordinal=1, review_status="auto_accepted")
    result = SpecialistResult(
        specialist_type="utility_bill",
        schema_version="utility_v1",
        review_status="auto_accepted",
        result_json={
            "issuer": "Acque S.p.A.",
            "due_date": "2026-08-31",
            "total_amount": 123.45,
            "currency": "EUR",
        },
    )

    evidence = _specialist_search_evidence(result, unit)

    assert evidence[0]["page_from"] == 2
    assert "Fornitore: Acque S.p.A." in evidence[0]["text"]
    assert "Scadenza: 2026-08-31" in evidence[0]["text"]
    assert "Importo: 123.45" in evidence[0]["text"]


def test_accounting_agent_tool_delegates_to_accounting_query_engine(monkeypatch):
    captured = {}

    def fake_ask(payload, db):
        captured["payload"] = payload
        captured["db"] = db
        return {"status": "answered", "answer": "computed", "evidence": []}

    monkeypatch.setattr(knowledge, "ask_accounting", fake_ask)
    action = _KnowledgeAgentAction.model_validate({
        "action": "query_accounting_tables",
        "query": "Confronta le spese di Bonacci",
        "document_id": "a61e4d32-9ce8-46bc-8bdf-f29c49285497",
        "subject": "Bonacci",
        "period_a_from": "2022-01-01",
        "period_a_to": "2022-12-31",
        "period_b_from": "2023-01-01",
        "period_b_to": "2023-12-31",
    })
    db = object()

    output = _run_knowledge_agent_tool(db, action, allow_vision=False)

    assert output["status"] == "answered"
    assert captured["db"] is db
    assert captured["payload"].subject == "Bonacci"
    assert captured["payload"].period_b_to.isoformat() == "2023-12-31"
