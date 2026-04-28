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
    DocumentUnit,
    DocumentUnitEntity,
    DocumentUnitTopicAssignment,
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
        self._finalize_matched_proposals()
        self.db.flush()
        stats.topics_after = int(
            self.db.execute(
                select(func.count()).select_from(Topic).where(Topic.is_active.is_(True))
            ).scalar_one()
        )
        return stats

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
