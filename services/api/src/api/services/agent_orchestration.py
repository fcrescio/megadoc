from __future__ import annotations

import re
from dataclasses import dataclass, field


SEARCH_ACTIONS = {"retrieve_evidence", "search_archive", "semantic_search", "search_document_text", "list_topics"}
READ_ACTIONS = {"get_page_text", "get_document", "get_document_unit"}
SPECIALIST_ACTIONS = {"search_calendar_events", "query_accounting_tables"}
VISION_ACTIONS = {"analyze_page_image", "request_page_vision"}


def canonical_query(value: str | None) -> str:
    terms = re.findall(r"[a-z0-9]+", (value or "").lower())
    return " ".join(sorted(dict.fromkeys(term for term in terms if len(term) >= 2)))


@dataclass
class AgentToolBudget:
    max_total: int = 8
    limits: dict[str, int] = field(default_factory=lambda: {
        "search": 3,
        "read": 4,
        "specialist": 2,
        "vision": 1,
        "other": 3,
    })
    counts: dict[str, int] = field(default_factory=dict)
    total: int = 0

    def consume(self, action: str) -> str | None:
        category = self.category(action)
        if self.total >= self.max_total:
            return f"total tool budget exhausted ({self.max_total})"
        used = self.counts.get(category, 0)
        limit = self.limits[category]
        if used >= limit:
            return f"{category} tool budget exhausted ({limit})"
        self.counts[category] = used + 1
        self.total += 1
        return None

    @staticmethod
    def category(action: str) -> str:
        if action in SEARCH_ACTIONS:
            return "search"
        if action in READ_ACTIONS:
            return "read"
        if action in SPECIALIST_ACTIONS:
            return "specialist"
        if action in VISION_ACTIONS:
            return "vision"
        return "other"
