import uuid

from scripts.backfill_canonical_entities import choose_display_value, collect_candidates
from common.db.models import Document, DocumentUnit, DocumentUnitEntity, ScanUnit


def _unit(db_session, filename: str, entities: list[DocumentUnitEntity]) -> DocumentUnit:
    document = Document(
        original_filename=filename,
        mime_type="application/pdf",
        sha256=uuid.uuid4().hex * 2,
        size_bytes=100,
        source_type="api",
    )
    scan_unit = ScanUnit(
        document=document,
        source_document_id=document.id,
        source_ocr_result_id=uuid.uuid4(),
        page_count=1,
        status="assigned",
    )
    unit = DocumentUnit(
        scan_unit=scan_unit,
        ordinal=1,
        start_page=1,
        end_page=1,
        review_status="auto_accepted",
    )
    unit.entities.extend(entities)
    db_session.add_all([document, scan_unit, unit])
    db_session.flush()
    return unit


def _entity(value: str, key: str, entity_type: str = "persona") -> DocumentUnitEntity:
    return DocumentUnitEntity(
        entity_type=entity_type,
        entity_value=value,
        normalized_value=key,
        confidence=0.9,
        page_from=1,
        page_to=1,
    )


def test_collect_candidates_requires_distinct_documents(db_session):
    _unit(
        db_session,
        "one.pdf",
        [
            _entity("Crescioli Francesco", "crescioli_francesco"),
            _entity("CRESCIOLI FRANCESCO", "crescioli_francesco"),
            _entity("One-off", "one_off"),
        ],
    )
    _unit(db_session, "two.pdf", [_entity("Francesco Crescioli", "crescioli_francesco")])

    candidates = collect_candidates(db_session, min_documents=2)

    assert [(item.entity_type, item.entity_key, item.document_count, item.mention_count) for item in candidates] == [
        ("persona", "crescioli_francesco", 2, 3)
    ]


def test_choose_display_value_prefers_frequent_short_form():
    assert (
        choose_display_value(["CRESCIOLI FRANCESCO", "Crescioli Francesco", "Crescioli Francesco"])
        == "Crescioli Francesco"
    )
