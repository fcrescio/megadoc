from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from common.application.contexts import ContextProjectionStats, rebuild_knowledge_contexts
from common.application.graph import GraphProjectionStats, rebuild_knowledge_graph
from common.db.models import (
    DocumentUnitMention,
    KnowledgeAssertion,
    KnowledgeContext,
    KnowledgeContextAnchor,
    KnowledgeContextMembership,
    KnowledgeNode,
    KnowledgeNodeAlias,
)


@dataclass(frozen=True)
class SemanticProjectionSnapshot:
    graph: GraphProjectionStats
    contexts: ContextProjectionStats
    fingerprint: str


def rebuild_semantic_projections(session: Session) -> SemanticProjectionSnapshot:
    graph = rebuild_knowledge_graph(session)
    contexts = rebuild_knowledge_contexts(session)
    return SemanticProjectionSnapshot(
        graph=graph,
        contexts=contexts,
        fingerprint=semantic_projection_fingerprint(session),
    )


def semantic_projection_fingerprint(session: Session) -> str:
    """Hash semantic projection content while ignoring generated IDs and timestamps."""
    nodes = {node.id: node for node in session.execute(select(KnowledgeNode)).scalars()}
    contexts = {row.id: row for row in session.execute(select(KnowledgeContext)).scalars()}
    payload = {
        "nodes": sorted(
            (node.node_kind, node.canonical_key, node.label, str(node.canonical_entity_id or ""), node.review_status)
            for node in nodes.values()
        ),
        "aliases": sorted(
            (nodes[row.node_id].node_kind, nodes[row.node_id].canonical_key, row.normalized_alias)
            for row in session.execute(select(KnowledgeNodeAlias)).scalars()
        ),
        "mentions": sorted(
            (str(row.document_unit_id), nodes[row.node_id].node_kind, nodes[row.node_id].canonical_key,
             row.mention_role, row.source_type, row.surface_text or "", row.page_from, row.page_to)
            for row in session.execute(select(DocumentUnitMention)).scalars()
        ),
        "assertions": sorted(
            (str(row.document_unit_id), row.predicate_code, row.value_text or "",
             json.dumps(row.value_json, sort_keys=True, default=str),
             nodes[row.object_node_id].canonical_key if row.object_node_id else "")
            for row in session.execute(select(KnowledgeAssertion)).scalars()
        ),
        "contexts": sorted(
            (row.context_kind, str(row.canonical_entity_id), row.label, row.review_status)
            for row in contexts.values()
        ),
        "anchors": sorted(
            (str(contexts[row.context_id].canonical_entity_id), str(row.canonical_entity_id), row.anchor_role)
            for row in session.execute(select(KnowledgeContextAnchor)).scalars()
        ),
        "memberships": sorted(
            (str(contexts[row.context_id].canonical_entity_id), str(row.document_unit_id),
             row.membership_role, row.source_type, json.dumps(row.evidence_json, sort_keys=True, default=str))
            for row in session.execute(select(KnowledgeContextMembership)).scalars()
        ),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
