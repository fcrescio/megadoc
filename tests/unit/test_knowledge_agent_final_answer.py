from api.routers.knowledge import (
    _agent_search_document_text,
    _KnowledgeAgentAction,
    _normalize_knowledge_agent_final,
    _build_question_presearch_context,
    _text_page_hit,
    _validate_knowledge_agent_final,
    KnowledgeAgentTraceStep,
)
from common.db.models import Document, DocumentVersion, OCRResult


def test_normalizes_final_answer_reasoning_and_top_level_page_reference():
    action = _KnowledgeAgentAction(
        action="final_answer",
        reasoning="La risposta verificata e' nella pagina letta.",
        document_id="doc-1",
        page_number=6,
    )
    trace = [
        KnowledgeAgentTraceStep(
            step=1,
            action="get_page_text",
            input={"document_id": "doc-1", "page_number": 6},
            output={"document_id": "doc-1", "page_number": 6, "text": "testo OCR"},
        )
    ]

    normalized = _normalize_knowledge_agent_final(action)

    assert normalized.answer == "La risposta verificata e' nella pagina letta."
    assert normalized.citations == [{"document_id": "doc-1", "page_from": 6, "page_to": 6}]
    assert _validate_knowledge_agent_final(normalized, trace) is None


def test_normalized_final_answer_still_requires_read_page_trace():
    action = _KnowledgeAgentAction(
        action="final_answer",
        reasoning="Risposta senza pagina letta.",
        document_id="doc-1",
        page_number=6,
    )

    normalized = _normalize_knowledge_agent_final(action)

    assert _validate_knowledge_agent_final(normalized, []) == (
        "each cited document/page must have been read with get_page_text or analyze_page_image before final_answer"
    )


def test_final_answer_accepts_page_image_analysis_as_evidence():
    action = _KnowledgeAgentAction(
        action="final_answer",
        answer="La pagina mostra una tabella leggibile.",
        citations=[{"document_id": "doc-1", "page_from": 2, "page_to": 2}],
    )
    trace = [
        KnowledgeAgentTraceStep(
            step=1,
            action="analyze_page_image",
            input={"document_id": "doc-1", "page_number": 2},
            output={
                "document_id": "doc-1",
                "page_number": 2,
                "analysis": {"page_summary": "Tabella con importi e intestazioni visibili."},
            },
        )
    ]

    assert _validate_knowledge_agent_final(action, trace) is None


def test_text_page_hit_scores_matching_query_terms():
    hit = _text_page_hit(
        "E' vietato l'uso smodato di radio e televisori prima delle ore 8 e dopo le 22.",
        ["riposo", "radio", "televisori", "ore"],
    )

    assert hit is not None
    assert hit[2] == 3


def test_final_answer_allows_supported_no_evidence_result():
    action = _KnowledgeAgentAction(
        action="final_answer",
        answer="Non ho trovato documenti che riportino il pagamento dell'imposta sulla casa nel 2007.",
    )
    trace = [
        KnowledgeAgentTraceStep(
            step=1,
            action="search_calendar_events",
            input={"query": "imposta casa", "date_from": "2007-01-01", "date_to": "2007-12-31"},
            output={"events": []},
        ),
        KnowledgeAgentTraceStep(
            step=2,
            action="search_document_text",
            input={"query": "ICI 2007 imposta casa"},
            output={"hits": []},
        ),
    ]

    assert _validate_knowledge_agent_final(action, trace) is None


def test_global_document_text_search_returns_citable_pages(db_session):
    document = Document(
        original_filename="ici.pdf",
        mime_type="application/pdf",
        sha256="1" * 64,
        size_bytes=10,
        source_type="upload",
    )
    db_session.add(document)
    db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        storage_bucket="documents",
        storage_object_key="ici.pdf",
    )
    db_session.add(version)
    db_session.flush()
    db_session.add(
        OCRResult(
            document_id=document.id,
            document_version_id=version.id,
            engine_name="fake",
            engine_version="test",
            pipeline_version="test",
            status="succeeded",
            full_text="",
            markdown_text="",
            structured_json={"pages": [{"page_number": 1, "text": "Ricevuta pagamento ICI anno 2007 euro 123,45"}]},
            page_count=1,
        )
    )
    db_session.commit()

    result = _agent_search_document_text(db_session, None, "ICI 2007", limit=5)

    assert result["scope"] == "archive"
    assert result["hits"][0]["document_id"] == str(document.id)
    assert result["hits"][0]["page_number"] == 1


def test_question_presearch_context_lists_candidate_pages(db_session):
    document = Document(
        original_filename="sepi.pdf",
        mime_type="application/pdf",
        sha256="2" * 64,
        size_bytes=10,
        source_type="upload",
    )
    db_session.add(document)
    db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        storage_bucket="documents",
        storage_object_key="sepi.pdf",
    )
    db_session.add(version)
    db_session.flush()
    db_session.add(
        OCRResult(
            document_id=document.id,
            document_version_id=version.id,
            engine_name="fake",
            engine_version="test",
            pipeline_version="test",
            status="succeeded",
            full_text="",
            markdown_text="",
            structured_json={"pages": [{"page_number": 1, "text": "Imposta Comunale Immobili Anno 2007 E. 664,67"}]},
            page_count=1,
        )
    )
    db_session.commit()

    context = _build_question_presearch_context(db_session, "quanto ho pagato di imposta sulla casa nel 2007?")

    assert str(document.id) in context
    assert "page=1" in context
