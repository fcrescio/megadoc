from dataclasses import dataclass

import pytest

import specialist_worker.registry as worker_registry
from common.application.specialist_contracts import (
    SpecialistExecutionContext,
    SpecialistExtraction,
    SpecialistPresentation,
    SpecialistRegistry,
    SpecialistValidation,
    attach_specialist_envelope,
)
from common.db.models import DocumentType, DocumentUnit


@dataclass
class DummyHandler:
    capability: str
    document_types: frozenset[str]
    schema_version: str = "dummy_v1"

    def extract(self, context):
        return SpecialistExtraction(payload={"value": "ok"}, confidence=0.9)

    def validate(self, extraction):
        return SpecialistValidation("valid")

    def project(self, session, document_unit, result):
        return None

    def present(self, payload):
        return SpecialistPresentation(title=self.capability)

    def reapply_corrections(self, payload, previous):
        return payload


def _unit(document_type: str = "fixture") -> DocumentUnit:
    unit = DocumentUnit(
        start_page=2,
        end_page=3,
        ordinal=1,
        review_status="auto_accepted",
        document_type_confidence=0.87,
    )
    unit.document_type = DocumentType(code=document_type, name=document_type)
    return unit


def test_registry_supports_multiple_and_no_specialists_without_core_changes():
    registry = SpecialistRegistry()
    registry.register(DummyHandler("first", frozenset({"fixture"})))
    registry.register(DummyHandler("second", frozenset({"fixture"})))

    candidates = registry.candidates(_unit())

    assert [candidate.capability for candidate in candidates] == ["first", "second"]
    assert all(candidate.confidence == 0.87 for candidate in candidates)
    assert registry.candidates(_unit("generic_letter")) == []


@pytest.mark.parametrize("capability", ["utility_bill", "accounting_statement"])
def test_builtin_specialists_follow_common_contract(monkeypatch, db_session, capability):
    unit = _unit("bolletta" if capability == "utility_bill" else "rendiconto_contabile")
    if capability == "utility_bill":
        monkeypatch.setattr(
            worker_registry,
            "process_utility_bill",
            lambda session, document_unit, text, input_version: (
                {"issuer": "Acque S.p.A.", "total_amount": 10.5, "due_date": "2026-08-01"},
                [],
                0.91,
            ),
        )
    else:
        monkeypatch.setattr(
            worker_registry,
            "process_accounting_statement",
            lambda *args, **kwargs: (
                {
                    "statement_type": "actual",
                    "tables": [{
                        "table_id": "t1", "page_number": 2, "headers": ["Voce", "Importo"],
                        "rows": [{"row_id": "r1", "cells": {"Voce": "Acqua", "Importo": "10,50"}}],
                    }],
                    "sections": [], "validation_checks": [],
                },
                0.92,
            ),
        )
    registry = worker_registry.build_specialist_registry(lambda: None)
    handler = registry.get(capability)
    extraction = handler.extract(SpecialistExecutionContext(
        session=db_session,
        document_unit=unit,
        text="Acque S.p.A. Totale EUR 10,50. Scadenza 01/08/2026.",
        structured_json={},
        input_version="fixture:v1",
    ))
    validation = handler.validate(extraction)
    presentation = handler.present(extraction.payload)
    envelope = attach_specialist_envelope(
        extraction, handler=handler, validation=validation, presentation=presentation
    )

    assert extraction.confidence > 0.9
    assert validation.status == "valid"
    assert presentation.title
    assert envelope["_specialist"]["capability"] == capability
    assert envelope["_specialist"]["schema_version"] == handler.schema_version
    assert envelope["_specialist"]["evidence"]


def test_utility_validation_rejects_values_not_grounded_in_source(monkeypatch, db_session):
    monkeypatch.setattr(
        worker_registry,
        "process_utility_bill",
        lambda session, document_unit, text, input_version: (
            {"issuer": "Toscana Energia", "total_amount": 7148428.17, "due_date": "2010-02-09"},
            [],
            0.95,
        ),
    )
    handler = worker_registry.build_specialist_registry(lambda: None).get("utility_bill")
    extraction = handler.extract(SpecialistExecutionContext(
        session=db_session,
        document_unit=_unit("bolletta"),
        text="Toscana Energia - importo 19,78 euro - scadenza 05/03/2009",
        structured_json={},
        input_version="fixture:v1",
    ))

    validation = handler.validate(extraction)

    assert validation.status == "needs_review"
    assert any("total_amount" in message for message in validation.messages)
    assert any("due_date" in message for message in validation.messages)


def test_registry_rejects_duplicate_capability():
    registry = SpecialistRegistry()
    registry.register(DummyHandler("duplicate", frozenset()))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(DummyHandler("duplicate", frozenset()))
