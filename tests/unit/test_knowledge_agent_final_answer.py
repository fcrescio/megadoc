from api.routers.knowledge import (
    _KnowledgeAgentAction,
    _normalize_knowledge_agent_final,
    _text_page_hit,
    _validate_knowledge_agent_final,
    KnowledgeAgentTraceStep,
)


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
        "each cited document/page must have been read with get_page_text before final_answer"
    )


def test_text_page_hit_scores_matching_query_terms():
    hit = _text_page_hit(
        "E' vietato l'uso smodato di radio e televisori prima delle ore 8 e dopo le 22.",
        ["riposo", "radio", "televisori", "ore"],
    )

    assert hit is not None
    assert hit[2] == 3
