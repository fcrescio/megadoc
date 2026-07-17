from api.routers import knowledge
from api.routers.knowledge import (
    _KnowledgeAgentAction,
    KnowledgeAgentChatRequest,
    _prepare_automatic_agent_evidence,
    _run_knowledge_agent_tool,
    _split_search_text,
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


def test_search_text_split_covers_tail_with_bounded_chunks():
    text = " ".join(f"token-{index}" for index in range(300))

    chunks = _split_search_text(text, max_chars=120, overlap=20)

    assert len(chunks) > 2
    assert all(len(chunk) <= 120 for chunk in chunks)
    assert "token-299" in chunks[-1]


def test_automatic_evidence_reads_ranked_pages_and_seeds_trace(monkeypatch):
    monkeypatch.setattr(
        knowledge,
        "_agent_retrieve_evidence",
        lambda db, query, document_id, limit: {
            "query": query,
            "results": [
                {"document_id": "doc-1", "page_from": 4, "metadata": {"original_filename": "one.pdf"}},
                {"document_id": "doc-1", "page_from": 4, "metadata": {}},
                {"document_id": "doc-2", "page_from": 7, "metadata": {"original_filename": "two.pdf"}},
            ],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        knowledge,
        "_agent_page_text",
        lambda db, document_id, page: {
            "document_id": document_id,
            "page_number": page,
            "text": f"evidence {document_id} page {page}",
        },
    )

    context, trace, signatures = _prepare_automatic_agent_evidence(
        object(), KnowledgeAgentChatRequest(question="spese ascensore"), page_limit=2
    )

    assert context.count("PAGINA LETTA AUTOMATICAMENTE") == 2
    assert "document_id: doc-1" in context
    assert [step.action for step in trace] == ["retrieve_evidence", "get_page_text", "get_page_text"]
    assert len(signatures) == 3
