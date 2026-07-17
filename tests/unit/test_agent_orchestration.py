from api.services.agent_orchestration import AgentToolBudget, canonical_query


def test_canonical_query_deduplicates_reordered_search_terms():
    assert canonical_query("Spese ASCENSORE, Bonacci") == canonical_query("Bonacci ascensore spese")


def test_tool_budget_enforces_category_and_total_limits():
    budget = AgentToolBudget(max_total=3, limits={
        "search": 1, "read": 2, "specialist": 1, "vision": 1, "other": 1,
    })

    assert budget.consume("retrieve_evidence") is None
    assert budget.consume("semantic_search") == "search tool budget exhausted (1)"
    assert budget.consume("get_page_text") is None
    assert budget.consume("get_document") is None
    assert budget.consume("query_accounting_tables") == "total tool budget exhausted (3)"
