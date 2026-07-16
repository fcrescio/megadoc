from __future__ import annotations

from collections.abc import Callable
from typing import Any


SearchProvider = Callable[[str, int], dict[str, Any]]


class RetrievalService:
    """Fuse lexical and vector evidence behind one stable interface."""

    def __init__(
        self,
        *,
        lexical_search: SearchProvider,
        semantic_search: SearchProvider | None = None,
        rrf_k: int = 60,
        max_per_document: int = 2,
    ) -> None:
        self._lexical_search = lexical_search
        self._semantic_search = semantic_search
        self._rrf_k = rrf_k
        self._max_per_document = max_per_document

    def retrieve(self, query: str, *, limit: int = 8) -> dict[str, Any]:
        query = query.strip()
        if not query:
            return {"query": query, "results": [], "warnings": ["query is empty"]}
        fetch_limit = max(limit * 3, 12)
        warnings: list[str] = []
        lexical = self._normalize_lexical(self._lexical_search(query, fetch_limit))
        semantic: list[dict[str, Any]] = []
        if self._semantic_search is not None:
            try:
                semantic = self._normalize_semantic(self._semantic_search(query, fetch_limit))
            except Exception as exc:
                warnings.append(f"semantic retrieval unavailable: {type(exc).__name__}: {exc}")
        else:
            warnings.append("semantic retrieval not configured")
        results = self.fuse_ranked(
            {"lexical": lexical, "semantic": semantic},
            limit=limit,
            rrf_k=self._rrf_k,
            max_per_document=self._max_per_document,
        )
        return {
            "query": query,
            "strategy": "rrf_lexical_semantic",
            "results": results,
            "warnings": warnings,
            "coverage": {"lexical": len(lexical), "semantic": len(semantic)},
        }

    @staticmethod
    def fuse_ranked(
        rankings: dict[str, list[dict[str, Any]]],
        *,
        limit: int,
        rrf_k: int = 60,
        max_per_document: int = 2,
    ) -> list[dict[str, Any]]:
        merged: dict[tuple[Any, ...], dict[str, Any]] = {}
        for channel, candidates in rankings.items():
            for rank, candidate in enumerate(candidates, start=1):
                key = RetrievalService._candidate_key(candidate)
                item = merged.setdefault(
                    key,
                    {
                        **candidate,
                        "rrf_score": 0.0,
                        "channels": [],
                        "ranks": {},
                        "evidence_sources": [],
                    },
                )
                source = {
                    "source_type": candidate.get("source_type"),
                    "source_id": candidate.get("source_id"),
                }
                if source not in item["evidence_sources"]:
                    item["evidence_sources"].append(source)
                if channel in item["ranks"]:
                    item["metadata"] = {**candidate.get("metadata", {}), **item.get("metadata", {})}
                    continue
                item["rrf_score"] += 1.0 / (rrf_k + rank)
                item["channels"].append(channel)
                item["ranks"][channel] = rank
                if not item.get("snippet") and candidate.get("snippet"):
                    item["snippet"] = candidate["snippet"]
                item["metadata"] = {**candidate.get("metadata", {}), **item.get("metadata", {})}
        ordered = sorted(
            merged.values(),
            key=lambda item: (
                -item["rrf_score"],
                str(item.get("document_id") or ""),
                item.get("page_from") or 0,
            ),
        )
        selected: list[dict[str, Any]] = []
        document_counts: dict[str, int] = {}
        for item in ordered:
            document_id = str(item.get("document_id") or "")
            if document_id and document_counts.get(document_id, 0) >= max_per_document:
                continue
            item["rrf_score"] = round(item["rrf_score"], 8)
            selected.append(item)
            if document_id:
                document_counts[document_id] = document_counts.get(document_id, 0) + 1
            if len(selected) >= limit:
                break
        return selected

    @staticmethod
    def _candidate_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
        document_id = candidate.get("document_id")
        page_from = candidate.get("page_from")
        page_to = candidate.get("page_to")
        if document_id and page_from is not None:
            return ("page", document_id, page_from, page_to or page_from)
        return (
            candidate.get("source_type"),
            candidate.get("source_id"),
            document_id,
            candidate.get("document_unit_id"),
        )

    @staticmethod
    def _normalize_lexical(payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "source_type": hit.get("source_type") or "ocr_page",
                "source_id": hit.get("source_id"),
                "document_id": hit.get("document_id"),
                "document_unit_id": hit.get("document_unit_id"),
                "page_from": hit.get("page_from", hit.get("page_number")),
                "page_to": hit.get("page_to", hit.get("page_number")),
                "snippet": hit.get("snippet"),
                "metadata": hit.get("metadata") or {"original_filename": hit.get("original_filename")},
                "channel_score": hit.get("score"),
            }
            for hit in payload.get("hits", [])
            if isinstance(hit, dict)
        ]

    @staticmethod
    def _normalize_semantic(payload: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "source_type": result.get("source_type"),
                "source_id": result.get("source_id"),
                "document_id": result.get("document_id"),
                "document_unit_id": result.get("document_unit_id"),
                "page_from": result.get("page_from"),
                "page_to": result.get("page_to"),
                "snippet": result.get("snippet"),
                "metadata": result.get("metadata") or {},
                "channel_score": result.get("score"),
            }
            for result in payload.get("results", [])
            if isinstance(result, dict)
        ]
