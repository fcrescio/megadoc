"""Batch-level topic consolidation for the knowledge base."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from common.db.models import (
    DocumentUnit,
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
        "from",
        "invoice",
        "fattura",
        "bill",
        "bolletta",
        "estimate",
        "preventivo",
        "construction",
        "works",
        "work",
        "cost",
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
        "building",
        "permit",
        "administrative",
        "declaration",
        "communication",
        "notice",
        "privacy",
        "data",
        "protection",
        "compliance",
        "maintenance",
        "correspondence",
        "relationship",
        "issue",
        "financial",
        "period",
        "general",
        "matter",
        "case",
        "file",
        "document",
        "documents",
        "contract",
        "supply",
    }

    _SIMILARITY_THRESHOLDS = {
        "vendor_relationship": 0.55,
        "financial_period": 0.62,
        "general_administration": 0.65,
        "legal_matter": 0.62,
        "case_file": 0.62,
        "building_issue": 0.58,
        "meeting": 0.68,
        "other": 0.72,
    }

    def __init__(self, db: Session) -> None:
        self.db = db

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
                selectinload(Topic.assignments).selectinload(DocumentUnitTopicAssignment.document_unit),
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
        for candidate in canonical_topics:
            score = self._topic_similarity(topic, candidate)
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
