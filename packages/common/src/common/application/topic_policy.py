from __future__ import annotations


TOPIC_KIND_ENTITY = "entity"

COLLECTION_KIND_BY_CLASS: dict[str, str] = {
    "vendor_relationship": "family",
    "financial_period": "family",
    "meeting": "family",
    "general_administration": "family",
    "building_issue": "issue",
    "case_file": "project",
    "legal_matter": "issue",
    "other": "context",
}

ASSIGNMENT_ROLE_BY_TOPIC_KIND: dict[str, str] = {
    "family": "document_family",
    "issue": "case_or_issue",
    "project": "case_or_issue",
    "context": "person_or_org_context",
}


def collection_topic_kind(topic_kind: str | None, topic_class: str | None) -> str:
    """Return a non-entity topic kind suitable for curated collections.

    Global identities live in canonical_entities. Topics group documents; they
    should not become a second person/building/vendor identity registry.
    """
    normalized_kind = (topic_kind or "").strip().lower()
    normalized_class = (topic_class or "other").strip().lower()
    if normalized_kind and normalized_kind != TOPIC_KIND_ENTITY:
        return normalized_kind
    return COLLECTION_KIND_BY_CLASS.get(normalized_class, "context")


def assignment_role_for_topic_kind(topic_kind: str | None) -> str:
    return ASSIGNMENT_ROLE_BY_TOPIC_KIND.get((topic_kind or "").strip().lower(), "secondary")
