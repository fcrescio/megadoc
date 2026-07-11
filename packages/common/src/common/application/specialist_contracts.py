from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from common.db.models import DocumentUnit, SpecialistResult


@dataclass(frozen=True)
class SpecialistCandidate:
    capability: str
    confidence: float
    rationale: str


@dataclass(frozen=True)
class SpecialistEvidence:
    field: str
    page_from: int
    page_to: int
    table_id: str | None = None
    row_id: str | None = None
    column_name: str | None = None
    raw_value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field,
            "page_from": self.page_from,
            "page_to": self.page_to,
            "table_id": self.table_id,
            "row_id": self.row_id,
            "column_name": self.column_name,
            "raw_value": self.raw_value,
        }


@dataclass
class SpecialistExtraction:
    payload: dict[str, Any]
    confidence: float
    evidence: list[SpecialistEvidence] = field(default_factory=list)
    links: list[Any] = field(default_factory=list)


@dataclass(frozen=True)
class SpecialistValidation:
    status: str
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class SpecialistPresentation:
    title: str
    summary: str | None = None
    fields: tuple[tuple[str, Any], ...] = ()


class SpecialistHandler(Protocol):
    capability: str
    schema_version: str
    document_types: frozenset[str]

    def extract(self, context: "SpecialistExecutionContext") -> SpecialistExtraction: ...
    def validate(self, extraction: SpecialistExtraction) -> SpecialistValidation: ...
    def project(self, session: Session, document_unit: DocumentUnit, result: SpecialistResult) -> None: ...
    def present(self, payload: dict[str, Any]) -> SpecialistPresentation: ...
    def reapply_corrections(self, payload: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class SpecialistExecutionContext:
    session: Session
    document_unit: DocumentUnit
    text: str
    structured_json: dict[str, Any]
    input_version: str


class SpecialistRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, SpecialistHandler] = {}

    def register(self, handler: SpecialistHandler) -> None:
        if handler.capability in self._handlers:
            raise ValueError(f"Specialist already registered: {handler.capability}")
        self._handlers[handler.capability] = handler

    def get(self, capability: str) -> SpecialistHandler:
        try:
            return self._handlers[capability]
        except KeyError as exc:
            raise ValueError(f"Unsupported specialist type: {capability}") from exc

    def candidates(self, document_unit: DocumentUnit) -> list[SpecialistCandidate]:
        document_type = document_unit.document_type.code if document_unit.document_type else None
        if not document_type:
            return []
        confidence = document_unit.document_type_confidence or 0.0
        return [
            SpecialistCandidate(
                capability=handler.capability,
                confidence=confidence,
                rationale=f"LLM document type '{document_type}' supports capability '{handler.capability}'.",
            )
            for handler in self._handlers.values()
            if document_type in handler.document_types
        ]

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(self._handlers)


def attach_specialist_envelope(
    extraction: SpecialistExtraction,
    *,
    handler: SpecialistHandler,
    validation: SpecialistValidation,
    presentation: SpecialistPresentation,
) -> dict[str, Any]:
    payload = dict(extraction.payload)
    payload["_specialist"] = {
        "capability": handler.capability,
        "schema_version": handler.schema_version,
        "confidence": extraction.confidence,
        "validation": {"status": validation.status, "messages": list(validation.messages)},
        "evidence": [item.to_dict() for item in extraction.evidence],
        "presentation": {
            "title": presentation.title,
            "summary": presentation.summary,
            "fields": [{"label": label, "value": value} for label, value in presentation.fields],
        },
    }
    return payload
