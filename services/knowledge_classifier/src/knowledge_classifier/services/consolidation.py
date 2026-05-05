"""Batch-level topic consolidation for the knowledge base."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from common.db.models import (
    CanonicalEntityVariant,
    DocumentUnit,
    DocumentUnitEntity,
    DocumentType,
    DocumentUnitTopicAssignment,
    GraphConsolidationReview,
    Topic,
    TopicAlias,
    TopicProposal,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ConsolidationStats:
    topics_before: int = 0
    topics_after: int = 0
    topics_merged: int = 0
    aliases_created: int = 0
    assignments_retargeted: int = 0
    proposals_retargeted: int = 0


@dataclass
class GraphSuggestionTopicSummary:
    id: str
    title: str
    slug: str
    topic_kind: str
    topic_class: str
    assignment_count: int
    dominant_assignment_role: str


@dataclass
class GraphMergeSuggestion:
    axis: str
    score: float
    rationale: str
    shared_entity_keys: list[str]
    shared_document_count: int
    source_topic: GraphSuggestionTopicSummary
    target_topic: GraphSuggestionTopicSummary


class KnowledgeBaseConsolidationService:
    _STOPWORDS = {
        "gen",
        "feb",
        "mar",
        "apr",
        "mag",
        "giu",
        "lug",
        "ago",
        "set",
        "ott",
        "nov",
        "dic",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "august",
        "september",
        "october",
        "november",
        "december",
        "from",
        "invoice",
        "fattura",
        "bill",
        "bolletta",
        "receipt",
        "receipts",
        "payment",
        "payments",
        "statement",
        "statements",
        "accounting",
        "record",
        "records",
        "estratto",
        "conto",
        "estimate",
        "preventivo",
        "quote",
        "quotations",
        "construction",
        "works",
        "work",
        "cost",
        "spese",
        "riparto",
        "consuntivo",
        "rendiconto",
        "final",
        "ordinary",
        "management",
        "for",
        "the",
        "and",
        "del",
        "della",
        "delle",
        "dei",
        "di",
        "comune",
        "condominio",
        "condominium",
        "building",
        "permit",
        "administrative",
        "administration",
        "administrator",
        "amministrazione",
        "amministratore",
        "declaration",
        "communication",
        "corrispondenza",
        "correspondence",
        "notice",
        "notification",
        "privacy",
        "data",
        "protection",
        "compliance",
        "maintenance",
        "relationship",
        "issue",
        "financial",
        "period",
        "balance",
        "budget",
        "utility",
        "utilities",
        "electricity",
        "water",
        "gas",
        "natural",
        "general",
        "matter",
        "case",
        "file",
        "document",
        "documents",
        "contract",
        "supply",
        "service",
        "services",
        "protocols",
        "guarantees",
        "tariffe",
        "tariff",
        "tariffs",
        "conditions",
        "schedule",
        "online",
        "access",
        "activation",
        "updates",
        "tax",
        "tarsu",
        "ici",
        "rai",
        "license",
        "licence",
        "property",
        "registration",
        "property",
        "cadastral",
        "catasto",
        "catasti",
        "spa",
        "srl",
        "snc",
        "spa",
        "ltd",
        "s.p.a",
        "s.r.l",
        "s.n.c",
    }

    _SIMILARITY_THRESHOLDS = {
        "vendor_relationship": 0.42,
        "financial_period": 0.34,
        "general_administration": 0.38,
        "legal_matter": 0.48,
        "case_file": 0.48,
        "building_issue": 0.45,
        "meeting": 0.4,
        "other": 0.72,
    }

    _CLASS_SIGNATURE_PREFIX = {
        "financial_period": "financial",
        "general_administration": "general",
        "vendor_relationship": "vendor",
        "meeting": "meeting",
        "legal_matter": "legal",
        "case_file": "case",
        "building_issue": "building",
        "other": "other",
    }

    _CLASS_ENTITY_PRIORITY = {
        "financial_period": ("condominio", "fornitore", "organizzazione", "indirizzo", "persona"),
        "general_administration": ("condominio", "organizzazione", "persona", "indirizzo", "fornitore"),
        "vendor_relationship": ("fornitore", "organizzazione", "persona", "indirizzo", "condominio"),
        "meeting": ("condominio", "indirizzo", "organizzazione", "persona"),
        "legal_matter": ("condominio", "fornitore", "organizzazione", "indirizzo", "persona"),
        "case_file": ("condominio", "indirizzo", "fornitore", "organizzazione", "persona"),
        "building_issue": ("condominio", "indirizzo", "fornitore", "organizzazione", "persona"),
        "other": ("organizzazione", "fornitore", "persona", "indirizzo", "condominio"),
    }

    _FAMILY_HINTS = {
        "regolamento": "regulation",
        "regulations": "regulation",
        "assemblea": "assembly",
        "assembly": "assembly",
        "verbale": "minutes",
        "minutes": "minutes",
        "preventivo": "quote",
        "quote": "quote",
        "fattura": "invoice",
        "invoice": "invoice",
        "bolletta": "invoice",
        "statement": "statement",
        "estratto": "statement",
        "contract": "contract",
        "contratto": "contract",
        "privacy": "privacy",
        "catasto": "cadastre",
        "cadastral": "cadastre",
        "tax": "tax",
        "tarsu": "tax",
        "ici": "tax",
        "rai": "tax",
    }

    _COMPATIBLE_CLASS_GROUPS = {
        "financial_period": "admin_finance",
        "general_administration": "admin_finance",
        "vendor_relationship": "admin_finance",
        "other": "admin_finance",
        "legal_matter": "matter",
        "case_file": "matter",
        "building_issue": "matter",
    }

    _AXIS_ROLE_MAP = {
        "subject": "subject",
        "person_or_org_context": "subject",
        "document_family": "document_family",
        "case_or_issue": "case_or_issue",
    }

    _AXIS_KIND_MAP = {
        "entity": "subject",
        "context": "subject",
        "family": "document_family",
        "issue": "case_or_issue",
        "project": "case_or_issue",
    }

    def __init__(self, db: Session) -> None:
        self.db = db
        self._signature_cache: dict[str, tuple[str, ...]] = {}

    def consolidate_topics(self) -> ConsolidationStats:
        stats = ConsolidationStats()
        topics = self.db.execute(self._topic_query(active_only=True)).scalars().all()
        if not topics:
            topics = self.db.execute(self._topic_query(active_only=False)).scalars().all()
        stats.topics_before = len(topics)

        by_class: dict[str, list[Topic]] = {}
        for topic in topics:
            by_class.setdefault(topic.topic_class, []).append(topic)

        for topic_class, class_topics in by_class.items():
            canonical_topics: list[Topic] = []
            threshold = self._SIMILARITY_THRESHOLDS.get(topic_class, 0.7)
            for topic in class_topics:
                canonical = self._find_canonical_topic(topic, canonical_topics, threshold)
                if canonical is None:
                    topic.is_active = True
                    topic.canonical = True
                    topic.updated_at = _utcnow()
                    canonical_topics.append(topic)
                    continue
                if canonical.id == topic.id:
                    continue
                self._merge_topic_into(canonical, topic, stats)

        self._signature_cache.clear()
        self._consolidate_compatible_groups(stats)
        self._normalize_meeting_topics(stats)
        self._normalize_accounting_family_topics(stats)
        self._finalize_matched_proposals()
        self.db.flush()
        stats.topics_after = int(
            self.db.execute(
                select(func.count()).select_from(Topic).where(Topic.is_active.is_(True))
            ).scalar_one()
        )
        return stats

    def suggest_graph_merges(self, limit_per_axis: int = 12) -> dict[str, list[GraphMergeSuggestion]]:
        topics = self.db.execute(self._topic_query(active_only=True)).scalars().all()
        canonical_map = self._canonical_entity_map()
        profiles = [self._build_topic_profile(topic, canonical_map) for topic in topics if topic.is_active]

        grouped: dict[str, list[dict[str, Any]]] = {
            "subject": [],
            "document_family": [],
            "case_or_issue": [],
        }
        for profile in profiles:
            if profile["axis"] in grouped:
                grouped[profile["axis"]].append(profile)

        suggestions: dict[str, list[GraphMergeSuggestion]] = {}
        reviewed_pairs = self._reviewed_graph_pairs()
        for axis, axis_profiles in grouped.items():
            axis_suggestions: list[GraphMergeSuggestion] = []
            for index, left in enumerate(axis_profiles):
                for right in axis_profiles[index + 1 :]:
                    suggestion = self._build_graph_merge_suggestion(axis, left, right)
                    if suggestion is not None and not self._is_reviewed_pair(reviewed_pairs, suggestion):
                        axis_suggestions.append(suggestion)
            axis_suggestions.sort(key=lambda item: (-item.score, item.target_topic.title, item.source_topic.title))
            suggestions[axis] = axis_suggestions[:limit_per_axis]
        return suggestions

    def review_graph_suggestion(
        self,
        *,
        axis: str,
        source_topic_id: str,
        target_topic_id: str,
        action: str,
        note: str | None = None,
        acted_by: str | None = None,
    ) -> int:
        source_topic = self.db.get(Topic, source_topic_id)
        target_topic = self.db.get(Topic, target_topic_id)
        if source_topic is None or target_topic is None:
            raise ValueError("Source or target topic not found.")
        affected_assignments = 0

        if action == "merge_into_target":
            stats = ConsolidationStats()
            self._merge_topic_into(target_topic, source_topic, stats)
            affected_assignments = stats.assignments_retargeted
        elif action == "convert_to_secondary_relationship":
            affected_assignments = self._convert_shared_assignments_to_secondary(source_topic, target_topic)
        elif action not in {"dismiss", "mark_same_subject_different_family"}:
            raise ValueError("Unsupported graph consolidation action.")

        review = GraphConsolidationReview(
            axis=axis,
            source_topic_id=source_topic.id,
            target_topic_id=target_topic.id,
            action=action,
            note=note,
            acted_by=acted_by,
        )
        self.db.add(review)
        self.db.flush()
        return affected_assignments

    def _topic_query(self, active_only: bool) -> Any:
        query = (
            select(Topic)
            .options(
                selectinload(Topic.assignments)
                .selectinload(DocumentUnitTopicAssignment.document_unit)
                .selectinload(DocumentUnit.entities),
                selectinload(Topic.proposals),
                selectinload(Topic.aliases),
            )
            .order_by(Topic.created_at.asc())
        )
        if active_only:
            query = query.where(Topic.is_active.is_(True))
        return query

    def _reviewed_graph_pairs(self) -> set[tuple[str, str, str]]:
        rows = self.db.execute(select(GraphConsolidationReview)).scalars().all()
        return {
            (row.axis, str(row.source_topic_id), str(row.target_topic_id))
            for row in rows
            if row.action in {
                "dismiss",
                "mark_same_subject_different_family",
                "convert_to_secondary_relationship",
                "merge_into_target",
            }
        }

    def _is_reviewed_pair(self, reviewed_pairs: set[tuple[str, str, str]], suggestion: GraphMergeSuggestion) -> bool:
        return (suggestion.axis, suggestion.source_topic.id, suggestion.target_topic.id) in reviewed_pairs

    def _canonical_entity_map(self) -> dict[tuple[str, str], str]:
        rows = self.db.execute(select(CanonicalEntityVariant)).scalars().all()
        mapping: dict[tuple[str, str], str] = {}
        for row in rows:
            mapping[(row.entity_type, row.entity_key)] = row.canonical_entity_id.hex
        return mapping

    def _build_topic_profile(self, topic: Topic, canonical_map: dict[tuple[str, str], str]) -> dict[str, Any]:
        role_counts = Counter(assignment.assignment_role for assignment in topic.assignments if assignment.assignment_role)
        dominant_role = role_counts.most_common(1)[0][0] if role_counts else "secondary"
        axis = self._AXIS_KIND_MAP.get(topic.topic_kind) or self._AXIS_ROLE_MAP.get(dominant_role)
        if axis is None:
            axis = "subject"
        family = self._topic_family(topic.title)

        document_ids: set[str] = set()
        entity_keys: set[str] = set()
        raw_entity_keys: set[str] = set()
        for assignment in topic.assignments:
            document_unit = assignment.document_unit
            if document_unit is None or document_unit.scan_unit is None:
                continue
            document_ids.add(str(document_unit.scan_unit.source_document_id))
            for entity in document_unit.entities:
                normalized = self._normalize_anchor_value(entity)
                if not normalized:
                    continue
                raw_key = f"{entity.entity_type}:{normalized}"
                raw_entity_keys.add(raw_key)
                canonical_id = canonical_map.get((entity.entity_type, normalized))
                if canonical_id:
                    entity_keys.add(f"{entity.entity_type}:canonical:{canonical_id}")
                else:
                    entity_keys.add(raw_key)

        return {
            "topic": topic,
            "axis": axis,
            "dominant_role": dominant_role,
            "family": family,
            "title_tokens": self._title_tokens(topic.title),
            "document_ids": document_ids,
            "entity_keys": entity_keys,
            "raw_entity_keys": raw_entity_keys,
            "weight": self._topic_weight(topic),
        }

    def _build_graph_merge_suggestion(
        self,
        axis: str,
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> GraphMergeSuggestion | None:
        entity_score, shared_entities = self._set_similarity(left["entity_keys"], right["entity_keys"])
        title_score, _ = self._set_similarity(left["title_tokens"], right["title_tokens"])
        doc_score, shared_docs = self._set_similarity(left["document_ids"], right["document_ids"])
        family_match = 1.0 if left.get("family") and left.get("family") == right.get("family") else 0.0

        if axis == "subject":
            score = (0.60 * entity_score) + (0.25 * title_score) + (0.15 * doc_score)
            threshold = 0.28
        elif axis == "document_family":
            score = (0.30 * entity_score) + (0.35 * title_score) + (0.20 * doc_score) + (0.15 * family_match)
            threshold = 0.32
        else:
            score = (0.35 * entity_score) + (0.25 * title_score) + (0.40 * doc_score)
            threshold = 0.30

        if entity_score == 0.0 and title_score == 0.0:
            return None
        if axis == "subject" and entity_score < 0.08 and title_score < 0.34:
            return None
        if score < threshold:
            return None

        left_topic: Topic = left["topic"]
        right_topic: Topic = right["topic"]
        target_profile, source_profile = self._pick_target_source(left, right)
        rationale_parts: list[str] = []
        if shared_entities:
            rationale_parts.append(f"shared entities: {', '.join(shared_entities[:3])}")
        if family_match:
            rationale_parts.append(f"same family {left['family']}")
        if title_score:
            rationale_parts.append(f"title overlap {title_score:.2f}")
        if shared_docs:
            rationale_parts.append(f"shared documents {len(shared_docs)}")

        return GraphMergeSuggestion(
            axis=axis,
            score=round(score, 3),
            rationale="; ".join(rationale_parts) or "graph similarity detected",
            shared_entity_keys=shared_entities[:5],
            shared_document_count=len(shared_docs),
            target_topic=GraphSuggestionTopicSummary(
                id=str(target_profile["topic"].id),
                title=target_profile["topic"].title,
                slug=target_profile["topic"].slug,
                topic_kind=target_profile["topic"].topic_kind,
                topic_class=target_profile["topic"].topic_class,
                assignment_count=len(target_profile["topic"].assignments),
                dominant_assignment_role=target_profile["dominant_role"],
            ),
            source_topic=GraphSuggestionTopicSummary(
                id=str(source_profile["topic"].id),
                title=source_profile["topic"].title,
                slug=source_profile["topic"].slug,
                topic_kind=source_profile["topic"].topic_kind,
                topic_class=source_profile["topic"].topic_class,
                assignment_count=len(source_profile["topic"].assignments),
                dominant_assignment_role=source_profile["dominant_role"],
            ),
        )

    def _pick_target_source(
        self,
        left: dict[str, Any],
        right: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if left["weight"] > right["weight"]:
            return left, right
        if right["weight"] > left["weight"]:
            return right, left
        left_topic: Topic = left["topic"]
        right_topic: Topic = right["topic"]
        if left_topic.created_at <= right_topic.created_at:
            return left, right
        return right, left

    def _convert_shared_assignments_to_secondary(self, source_topic: Topic, target_topic: Topic) -> int:
        target_document_ids = {
            str(assignment.document_unit.scan_unit.source_document_id)
            for assignment in target_topic.assignments
            if assignment.document_unit and assignment.document_unit.scan_unit
        }
        affected = 0
        for assignment in source_topic.assignments:
            document_unit = assignment.document_unit
            if document_unit is None or document_unit.scan_unit is None:
                continue
            document_id = str(document_unit.scan_unit.source_document_id)
            if document_id not in target_document_ids:
                continue
            if assignment.assignment_role != "secondary":
                assignment.assignment_role = "secondary"
                affected += 1
        source_topic.updated_at = _utcnow()
        return affected

    def _set_similarity(self, left: set[str], right: set[str]) -> tuple[float, list[str]]:
        if not left or not right:
            return 0.0, []
        shared = sorted(left & right)
        union = left | right
        return (len(shared) / len(union) if union else 0.0), shared

    def _find_canonical_topic(
        self,
        topic: Topic,
        canonical_topics: list[Topic],
        threshold: float,
    ) -> Topic | None:
        best_match: Topic | None = None
        best_score = 0.0
        topic_signature = self._topic_signature(topic)
        for candidate in canonical_topics:
            candidate_signature = self._topic_signature(candidate)
            if topic_signature and candidate_signature and topic_signature == candidate_signature:
                score = 1.0
            else:
                signature_score = self._signature_similarity(topic_signature, candidate_signature)
                token_score = self._topic_similarity(topic, candidate)
                score = max(signature_score, token_score)
            if score >= threshold and score > best_score:
                best_match = candidate
                best_score = score
        return best_match

    def _topic_similarity(self, left: Topic, right: Topic) -> float:
        left_tokens = self._title_tokens(left.title)
        right_tokens = self._title_tokens(right.title)
        if not left_tokens or not right_tokens:
            return 0.0
        intersection = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        token_score = intersection / union if union else 0.0

        left_join = " ".join(sorted(left_tokens))
        right_join = " ".join(sorted(right_tokens))
        contains_bonus = 0.15 if left_join and (left_join in right_join or right_join in left_join) else 0.0
        return min(1.0, token_score + contains_bonus)

    def _title_tokens(self, value: str) -> set[str]:
        raw_tokens = re.findall(r"[a-z0-9]{3,}", value.lower())
        normalized = set()
        for token in raw_tokens:
            if token.isdigit():
                continue
            if token in self._STOPWORDS:
                continue
            normalized.add(token)
        return normalized

    def _topic_signature(self, topic: Topic) -> tuple[str, ...]:
        cache_key = str(topic.id)
        if cache_key in self._signature_cache:
            return self._signature_cache[cache_key]

        prefix = self._CLASS_SIGNATURE_PREFIX.get(topic.topic_class, topic.topic_class)
        anchors = self._topic_anchor_parts(topic)
        family = self._topic_family(topic.title)
        signature_parts: list[str] = [prefix]

        if topic.topic_class == "financial_period":
            if anchors["condominio"]:
                signature_parts.append(anchors["condominio"])
                if family:
                    signature_parts.append(family)
            elif anchors["fornitore"] or anchors["organizzazione"]:
                signature_parts.append(anchors["fornitore"] or anchors["organizzazione"])
                secondary = anchors["persona"] or anchors["indirizzo"] or anchors["condominio"]
                if secondary:
                    signature_parts.append(secondary)
                if family:
                    signature_parts.append(family)
        elif topic.topic_class == "general_administration":
            primary = anchors["condominio"] or anchors["organizzazione"] or anchors["persona"] or anchors["indirizzo"]
            if primary:
                signature_parts.append(primary)
                secondary = anchors["organizzazione"] or anchors["persona"]
                if secondary and secondary != primary:
                    signature_parts.append(secondary)
                if family:
                    signature_parts.append(family)
        elif topic.topic_class == "meeting":
            primary = anchors["condominio"] or anchors["indirizzo"] or anchors["organizzazione"]
            if primary:
                signature_parts.append(primary)
                signature_parts.append("assembly")
        elif topic.topic_class == "vendor_relationship":
            primary = anchors["fornitore"] or anchors["organizzazione"]
            if primary:
                signature_parts.append(primary)
                secondary = anchors["persona"] or anchors["indirizzo"] or anchors["condominio"]
                if secondary:
                    signature_parts.append(secondary)
                if family:
                    signature_parts.append(family)
        else:
            primary = (
                anchors["condominio"]
                or anchors["fornitore"]
                or anchors["organizzazione"]
                or anchors["indirizzo"]
                or anchors["persona"]
            )
            if primary:
                signature_parts.append(primary)
                if family:
                    signature_parts.append(family)

        if len(signature_parts) == 1:
            fallback_tokens = sorted(self._title_tokens(topic.title))
            signature_parts.extend(fallback_tokens[:3])

        signature = tuple(part for part in signature_parts if part)
        self._signature_cache[cache_key] = signature
        return signature

    def _topic_anchor_parts(self, topic: Topic) -> dict[str, str | None]:
        counts: dict[str, Counter[str]] = {
            entity_type: Counter()
            for entity_type in ("condominio", "fornitore", "organizzazione", "indirizzo", "persona")
        }
        for assignment in topic.assignments:
            document_unit = assignment.document_unit
            if document_unit is None:
                continue
            for entity in document_unit.entities:
                if entity.entity_type not in counts:
                    continue
                anchor = self._normalize_anchor_value(entity)
                if anchor:
                    counts[entity.entity_type][anchor] += 1

        preferred = self._CLASS_ENTITY_PRIORITY.get(topic.topic_class, ())
        ordered_counts = {entity_type: counts[entity_type] for entity_type in preferred if entity_type in counts}
        ordered_counts.update({entity_type: counter for entity_type, counter in counts.items() if entity_type not in ordered_counts})

        result: dict[str, str | None] = {key: None for key in counts}
        for entity_type, counter in ordered_counts.items():
            if not counter:
                continue
            best_value = sorted(counter.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))[0][0]
            result[entity_type] = best_value
        return result

    def _normalize_anchor_value(self, entity: DocumentUnitEntity) -> str:
        raw_value = (entity.normalized_value or entity.entity_value or "").lower()
        raw_tokens = re.findall(r"[a-z0-9]{2,}", raw_value.replace("_", " "))
        tokens: list[str] = []
        for token in raw_tokens:
            if token.isdigit():
                continue
            if token in self._STOPWORDS:
                continue
            if len(token) < 3:
                continue
            tokens.append(token)
        if not tokens:
            return ""
        seen: list[str] = []
        for token in tokens:
            if token not in seen:
                seen.append(token)
        return "_".join(seen[:3])

    def _topic_family(self, title: str) -> str | None:
        title_lower = title.lower()
        for needle, family in self._FAMILY_HINTS.items():
            if needle in title_lower:
                return family
        return None

    def _signature_similarity(self, left: tuple[str, ...], right: tuple[str, ...]) -> float:
        if not left or not right:
            return 0.0
        left_set = set(left)
        right_set = set(right)
        intersection = len(left_set & right_set)
        union = len(left_set | right_set)
        return intersection / union if union else 0.0

    def _topic_weight(self, topic: Topic) -> tuple[int, int, float]:
        assignment_count = len(topic.assignments)
        proposal_count = len(topic.proposals)
        confidence_total = sum(
            assignment.confidence or 0.0 for assignment in topic.assignments
        ) + sum(proposal.confidence or 0.0 for proposal in topic.proposals)
        return assignment_count, proposal_count, confidence_total

    def _merge_topic_into(self, canonical: Topic, duplicate: Topic, stats: ConsolidationStats) -> None:
        if self._topic_weight(duplicate) > self._topic_weight(canonical):
            canonical, duplicate = duplicate, canonical

        canonical.is_active = True
        canonical.canonical = True
        existing_assignments = {
            (assignment.document_unit_id, assignment.assignment_role): assignment
            for assignment in canonical.assignments
        }
        for assignment in list(duplicate.assignments):
            key = (assignment.document_unit_id, assignment.assignment_role)
            existing = existing_assignments.get(key)
            if existing is None:
                assignment.topic_id = canonical.id
                canonical.assignments.append(assignment)
                existing_assignments[key] = assignment
            else:
                existing.confidence = max(existing.confidence or 0.0, assignment.confidence or 0.0) or None
                if not existing.rationale and assignment.rationale:
                    existing.rationale = assignment.rationale
                self.db.delete(assignment)
            stats.assignments_retargeted += 1

        for proposal in list(duplicate.proposals):
            proposal.matched_existing_topic_id = canonical.id
            stats.proposals_retargeted += 1

        alias_values = {
            canonical.slug.lower(),
            canonical.title.lower(),
            *(alias.alias.lower() for alias in canonical.aliases),
        }
        for candidate_alias in (duplicate.slug, duplicate.title):
            if candidate_alias.lower() not in alias_values:
                self.db.add(TopicAlias(topic_id=canonical.id, alias=candidate_alias))
                alias_values.add(candidate_alias.lower())
                stats.aliases_created += 1

        canonical.updated_at = _utcnow()
        duplicate.is_active = False
        duplicate.canonical = False
        duplicate.updated_at = _utcnow()
        stats.topics_merged += 1
        self._signature_cache.pop(str(canonical.id), None)
        self._signature_cache.pop(str(duplicate.id), None)

    def _normalize_meeting_topics(self, stats: ConsolidationStats) -> None:
        active_topics = self.db.execute(self._topic_query(active_only=True)).scalars().all()
        clusters: dict[str, list[Topic]] = {}
        for topic in active_topics:
            key = self._meeting_cluster_key(topic)
            if key:
                clusters.setdefault(key, []).append(topic)

        for cluster_topics in clusters.values():
            family_topics = [topic for topic in cluster_topics if topic.topic_class == "meeting"]
            if not family_topics:
                continue

            canonical = max(family_topics, key=self._topic_weight)
            for topic in family_topics:
                if topic.id == canonical.id or not topic.is_active:
                    continue
                self._merge_topic_into(canonical, topic, stats)

            self._rename_topic_to_meeting_family(canonical, stats)
            self._ensure_meeting_family_assignments(canonical, cluster_topics)

        active_topics = self.db.execute(self._topic_query(active_only=True)).scalars().all()
        family_groups: dict[str, list[Topic]] = {}
        for topic in active_topics:
            if topic.topic_class != "meeting" or topic.topic_kind != "family" or not topic.is_active:
                continue
            signature = self._meeting_family_signature(topic)
            if signature:
                family_groups.setdefault(signature, []).append(topic)

        for grouped_topics in family_groups.values():
            if len(grouped_topics) < 2:
                continue
            canonical = max(grouped_topics, key=self._topic_weight)
            for topic in grouped_topics:
                if topic.id == canonical.id or not topic.is_active:
                    continue
                self._merge_topic_into(canonical, topic, stats)
            self._rename_topic_to_meeting_family(canonical, stats)

    def _meeting_cluster_key(self, topic: Topic) -> str | None:
        if topic.topic_class != "meeting":
            return None

        anchors = self._topic_anchor_parts(topic)
        primary = anchors["condominio"] or anchors["indirizzo"] or anchors["organizzazione"]
        if primary:
            return f"meeting:{primary}"

        fallback_tokens = sorted(self._title_tokens(topic.title))
        if not fallback_tokens:
            return None
        return f"meeting:{'_'.join(fallback_tokens[:3])}"

    def _meeting_generic_title(self, topic: Topic) -> str:
        label = self._topic_anchor_display_value(topic)
        if label:
            return f"Assemblee condominiali - {label}"
        return "Assemblee condominiali"

    def _meeting_family_signature(self, topic: Topic) -> str | None:
        tokens = sorted(
            self._title_tokens(f"{topic.title} {topic.description or ''}")
            - {"verbale", "assemblea", "condominiale", "condominiali", "ordinaria", "straordinaria"}
        )
        if not tokens:
            anchors = self._topic_anchor_parts(topic)
            primary = anchors["condominio"] or anchors["indirizzo"] or anchors["organizzazione"]
            if not primary:
                return None
            return f"meeting-family:{primary}"
        return f"meeting-family:{'_'.join(tokens[:4])}"

    def _meeting_generic_slug(self, topic: Topic) -> str:
        return self._slugify(self._meeting_generic_title(topic))

    def _rename_topic_to_meeting_family(self, topic: Topic, stats: ConsolidationStats) -> None:
        generic_title = self._meeting_generic_title(topic)
        generic_slug = self._meeting_generic_slug(topic)
        alias_values = {
            topic.slug.lower(),
            topic.title.lower(),
            *(alias.alias.lower() for alias in topic.aliases),
        }
        for candidate_alias in (topic.slug, topic.title):
            if candidate_alias.lower() not in alias_values:
                self.db.add(TopicAlias(topic_id=topic.id, alias=candidate_alias))
                alias_values.add(candidate_alias.lower())
                stats.aliases_created += 1

        if topic.title != generic_title:
            if topic.title.lower() not in alias_values:
                self.db.add(TopicAlias(topic_id=topic.id, alias=topic.title))
                alias_values.add(topic.title.lower())
                stats.aliases_created += 1
            topic.title = generic_title
        unique_slug = self._unique_topic_slug(generic_slug, topic.id)
        if topic.slug != unique_slug:
            if topic.slug.lower() not in alias_values:
                self.db.add(TopicAlias(topic_id=topic.id, alias=topic.slug))
                alias_values.add(topic.slug.lower())
                stats.aliases_created += 1
            topic.slug = unique_slug
        topic.topic_kind = "family"
        topic.topic_class = "meeting"
        topic.updated_at = _utcnow()
        self._signature_cache.pop(str(topic.id), None)

    def _ensure_meeting_family_assignments(self, canonical: Topic, cluster_topics: list[Topic]) -> None:
        touched_units: set[str] = set()
        for topic in cluster_topics:
            for assignment in list(topic.assignments):
                document_unit = assignment.document_unit
                if document_unit is None:
                    continue
                document_type = document_unit.document_type
                if document_type is not None and document_type.code != "verbale_assemblea":
                    continue
                unit_key = str(document_unit.id)
                if unit_key in touched_units:
                    continue
                touched_units.add(unit_key)
                has_assignment = any(
                    existing.topic_id == canonical.id and existing.assignment_role == "document_family"
                    for existing in document_unit.topic_assignments
                )
                if has_assignment:
                    continue
                self.db.add(
                    DocumentUnitTopicAssignment(
                        document_unit_id=document_unit.id,
                        topic_id=canonical.id,
                        assignment_role="document_family",
                        confidence=assignment.confidence,
                        rationale="Meeting-family consolidation created an umbrella assembly topic.",
                    )
                )

    def _topic_anchor_display_value(self, topic: Topic) -> str | None:
        counts: dict[str, Counter[str]] = {
            entity_type: Counter()
            for entity_type in ("condominio", "indirizzo", "organizzazione")
        }
        for assignment in topic.assignments:
            document_unit = assignment.document_unit
            if document_unit is None:
                continue
            for entity in document_unit.entities:
                if entity.entity_type not in counts:
                    continue
                display_value = (entity.entity_value or "").strip()
                if display_value:
                    counts[entity.entity_type][display_value] += 1

        for entity_type in ("condominio", "indirizzo", "organizzazione"):
            counter = counts[entity_type]
            if counter:
                return sorted(counter.items(), key=lambda item: (-item[1], -len(item[0]), item[0]))[0][0]

        title = topic.title.strip()
        if " - " in title:
            return title.split(" - ", 1)[1].strip()
        return None

    def _normalize_accounting_family_topics(self, stats: ConsolidationStats) -> None:
        accounting_units = self.db.execute(
            select(DocumentUnit)
            .options(
                selectinload(DocumentUnit.document_type),
                selectinload(DocumentUnit.entities),
                selectinload(DocumentUnit.topic_assignments).selectinload(DocumentUnitTopicAssignment.topic),
            )
            .join(DocumentUnit.document_type)
            .where(func.lower(DocumentType.code).in_(("rendiconto_contabile", "riparto_spese")))
        ).scalars().all()

        clusters: dict[str, list[DocumentUnit]] = {}
        labels: dict[str, str] = {}
        for document_unit in accounting_units:
            anchor, label = self._document_unit_accounting_anchor(document_unit)
            if not anchor:
                continue
            clusters.setdefault(anchor, []).append(document_unit)
            labels.setdefault(anchor, label or "Rendiconti condominiali")

        for anchor, units in clusters.items():
            canonical = self._resolve_accounting_canonical_topic(units, labels[anchor])
            self._rename_topic_to_accounting_family(canonical, labels[anchor], stats)
            for document_unit in units:
                self._ensure_accounting_family_assignment(document_unit, canonical, stats)

    def _document_unit_accounting_anchor(self, document_unit: DocumentUnit) -> tuple[str | None, str | None]:
        normalized_candidates: dict[str, str] = {}
        for entity in document_unit.entities:
            if entity.entity_type not in {"condominio", "indirizzo"}:
                continue
            normalized = self._normalize_anchor_value(entity)
            if not normalized:
                continue
            normalized_candidates.setdefault(normalized, entity.entity_value.strip())

        if normalized_candidates:
            anchor, label = sorted(normalized_candidates.items(), key=lambda item: (-len(item[0]), item[0]))[0]
            return anchor, label
        return None, None

    def _resolve_accounting_canonical_topic(self, units: list[DocumentUnit], label: str) -> Topic:
        candidate_topics: list[Topic] = []
        for document_unit in units:
            for assignment in document_unit.topic_assignments:
                topic = assignment.topic
                if topic is None:
                    continue
                if topic.topic_class == "financial_period":
                    candidate_topics.append(topic)

        if candidate_topics:
            canonical = max(candidate_topics, key=self._topic_weight)
            canonical.is_active = True
            canonical.canonical = True
            canonical.topic_class = "financial_period"
            canonical.topic_kind = "family"
            return canonical

        base_title = f"Rendiconti Condominiali - {label}"
        base_slug = self._slugify(base_title)
        existing = self.db.execute(select(Topic).where(Topic.slug == base_slug)).scalar_one_or_none()
        if existing is not None:
            existing.is_active = True
            existing.canonical = True
            existing.topic_class = "financial_period"
            existing.topic_kind = "family"
            return existing

        topic = Topic(
            slug=base_slug,
            title=base_title,
            topic_class="financial_period",
            topic_kind="family",
            description="Topic ombrello per rendiconti, riparti e bilanci dello stesso condominio.",
            canonical=True,
            is_active=True,
        )
        self.db.add(topic)
        self.db.flush()
        return topic

    def _rename_topic_to_accounting_family(self, topic: Topic, label: str, stats: ConsolidationStats) -> None:
        generic_title = f"Rendiconti Condominiali - {label}"
        generic_slug = self._slugify(generic_title)
        alias_values = {
            topic.slug.lower(),
            topic.title.lower(),
            *(alias.alias.lower() for alias in topic.aliases),
        }
        for candidate_alias in (topic.slug, topic.title):
            if candidate_alias.lower() not in alias_values:
                self.db.add(TopicAlias(topic_id=topic.id, alias=candidate_alias))
                alias_values.add(candidate_alias.lower())
                stats.aliases_created += 1

        if topic.title != generic_title:
            if topic.title.lower() not in alias_values:
                self.db.add(TopicAlias(topic_id=topic.id, alias=topic.title))
                stats.aliases_created += 1
            topic.title = generic_title

        unique_slug = self._unique_topic_slug(generic_slug, topic.id)
        if topic.slug != unique_slug:
            if topic.slug.lower() not in alias_values:
                self.db.add(TopicAlias(topic_id=topic.id, alias=topic.slug))
                stats.aliases_created += 1
            topic.slug = unique_slug

        topic.topic_kind = "family"
        topic.topic_class = "financial_period"
        topic.is_active = True
        topic.canonical = True
        topic.updated_at = _utcnow()
        self._signature_cache.pop(str(topic.id), None)

    def _ensure_accounting_family_assignment(self, document_unit: DocumentUnit, canonical: Topic, stats: ConsolidationStats) -> None:
        existing_financial = None
        removable_meeting_assignments: list[DocumentUnitTopicAssignment] = []
        for assignment in list(document_unit.topic_assignments):
            topic = assignment.topic
            if topic is None:
                continue
            if topic.id == canonical.id and assignment.assignment_role == "document_family":
                existing_financial = assignment
            if topic.topic_class == "meeting" and topic.topic_kind == "family":
                removable_meeting_assignments.append(assignment)

        if existing_financial is None:
            self.db.add(
                DocumentUnitTopicAssignment(
                    document_unit_id=document_unit.id,
                    topic_id=canonical.id,
                    assignment_role="document_family",
                    confidence=0.92,
                    rationale="Accounting-family normalization created an umbrella financial topic for the condominium.",
                )
            )
            stats.assignments_retargeted += 1

        for assignment in removable_meeting_assignments:
            self.db.delete(assignment)
            stats.assignments_retargeted += 1

    def _slugify(self, value: str) -> str:
        normalized = value.lower()
        normalized = re.sub(r"[^a-z0-9]+", "-", normalized)
        normalized = re.sub(r"-{2,}", "-", normalized)
        return normalized.strip("-")[:255] or "topic"

    def _unique_topic_slug(self, base_slug: str, topic_id: Any | None = None) -> str:
        candidate = base_slug
        suffix = 2
        while True:
            existing = self.db.execute(select(Topic).where(Topic.slug == candidate)).scalar_one_or_none()
            if existing is None or (topic_id is not None and existing.id == topic_id):
                return candidate
            candidate = f"{base_slug[:240]}-{suffix}"
            suffix += 1

    def _consolidate_compatible_groups(self, stats: ConsolidationStats) -> None:
        active_topics = self.db.execute(self._topic_query(active_only=True)).scalars().all()
        grouped: dict[tuple[str, ...], list[Topic]] = {}
        for topic in active_topics:
            signature = self._cross_class_signature(topic)
            if signature:
                grouped.setdefault(signature, []).append(topic)

        for signature_topics in grouped.values():
            if len(signature_topics) < 2:
                continue
            canonical = max(signature_topics, key=self._topic_weight)
            for topic in signature_topics:
                if topic.id == canonical.id or not topic.is_active:
                    continue
                self._merge_topic_into(canonical, topic, stats)

    def _cross_class_signature(self, topic: Topic) -> tuple[str, ...]:
        family = self._topic_family(topic.title)
        group = self._cross_class_group(topic.topic_class, family)
        if group is None:
            return ()

        anchors = self._topic_anchor_parts(topic)
        if group == "admin_finance":
            primary = anchors["fornitore"] or anchors["organizzazione"]
            if primary:
                signature = [group, primary]
                secondary = anchors["condominio"] or anchors["persona"] or anchors["indirizzo"]
                if secondary and secondary != primary:
                    signature.append(secondary)
                return tuple(signature)

            primary = anchors["condominio"] or anchors["persona"] or anchors["indirizzo"]
            if primary:
                signature = [group, primary]
                if family in {"tax", "statement", "cadastre", "privacy"}:
                    signature.append(family)
                return tuple(signature)
            return ()

        primary = (
            anchors["condominio"]
            or anchors["fornitore"]
            or anchors["organizzazione"]
            or anchors["indirizzo"]
            or anchors["persona"]
        )
        if not primary:
            return ()
        signature = [group, primary]
        if family:
            signature.append(family)
        return tuple(signature)

    def _cross_class_group(self, topic_class: str, family: str | None) -> str | None:
        if topic_class == "legal_matter" and family in {"privacy", "contract", "tax", "cadastre"}:
            return "admin_finance"
        if topic_class == "case_file" and family in {"tax", "cadastre"}:
            return "admin_finance"
        return self._COMPATIBLE_CLASS_GROUPS.get(topic_class)

    def _finalize_matched_proposals(self) -> None:
        matched_proposals = self.db.execute(
            select(TopicProposal).where(
                TopicProposal.proposal_status == "proposed",
                TopicProposal.matched_existing_topic_id.is_not(None),
            )
        ).scalars().all()

        for proposal in matched_proposals:
            proposal.proposal_status = "merged_into_existing"
            proposal.reviewed_at = proposal.reviewed_at or _utcnow()
