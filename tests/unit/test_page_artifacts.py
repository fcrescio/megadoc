from pathlib import Path
from uuid import uuid4

from common.application.page_artifacts import (
    add_page_artifacts_to_structured_json,
    build_page_artifacts,
    get_page_artifact_text,
)
from common.application.services import OCRService
from common.db.models import Document, DocumentVersion, IngestionJob
from common.domain.enums import JobStatus, JobType, SourceType


def test_build_page_artifacts_records_per_page_provenance():
    structured = {
        "backend": "dots_native",
        "orientation_preprocess": {
            "rotation_applied": 180,
            "page_rotations": {"1": 180, "2": 90, "3": 0},
            "review_pages": [3],
            "page_order_reversed": True,
        },
        "pages": [
            {
                "page_number": 1,
                "text": "Native text from page one",
                "markdown": "# Page one",
                "width": 595,
                "height": 842,
                "metadata": {"mode": "layout", "confidence": 0.93},
                "blocks": [{"type": "heading", "text": "Page one"}],
            },
            {
                "page_number": 2,
                "text": "OCR text from page two",
                "metadata": {"mode": "ocr", "confidence": 0.88},
            },
            {
                "page_number": 3,
                "text": "",
                "metadata": {"mode": "empty"},
            },
        ],
    }

    artifacts = build_page_artifacts(
        structured_json=structured,
        markdown_text="",
        full_text="",
        page_count=3,
        engine_name="dots_native",
        engine_version="fixture-model",
    )

    assert [artifact.page_number for artifact in artifacts] == [1, 2, 3]
    assert artifacts[0].text_origin == "native"
    assert artifacts[0].page_class == "native"
    assert artifacts[0].rotation_applied == 180
    assert artifacts[0].page_order_reversed is True
    assert artifacts[1].text_origin == "ocr"
    assert artifacts[1].page_class == "scan"
    assert artifacts[1].rotation_applied == 90
    assert artifacts[2].text_origin == "failed"
    assert artifacts[2].rotation_applied == 0
    assert "orientation_needs_review" in artifacts[2].quality_flags
    assert "empty_text" in artifacts[2].quality_flags


def test_build_page_artifacts_fills_missing_structured_pages_from_markdown_markers():
    artifacts = build_page_artifacts(
        structured_json={
            "pages": [
                {
                    "page_number": 1,
                    "text": "Structured page one",
                    "metadata": {"mode": "ocr"},
                }
            ]
        },
        markdown_text="--- Page 1 ---\nStructured page one\n--- Page 2 ---\nFallback page two",
        full_text="",
        page_count=2,
    )

    assert len(artifacts) == 2
    assert artifacts[0].text == "Structured page one"
    assert artifacts[1].text == "Fallback page two"
    assert artifacts[1].text_origin == "unknown"
    assert "fallback_split" in artifacts[1].quality_flags


def test_get_page_artifact_text_prefers_materialized_artifact():
    structured = add_page_artifacts_to_structured_json(
        structured_json={"pages": [{"page_number": 1, "text": "raw page"}]},
        markdown_text="",
        full_text="",
        page_count=1,
        engine_name="fixture",
    )
    structured["page_artifacts"][0]["markdown"] = "curated page"

    assert (
        get_page_artifact_text(
            structured_json=structured,
            markdown_text="fallback",
            full_text="fallback",
            page_count=1,
            page_number=1,
        )
        == "curated page"
    )


def test_ocr_service_materializes_page_artifacts(db_session, valid_pdf_path: Path):
    document = Document(
        original_filename="sample.pdf",
        mime_type="application/pdf",
        sha256="abc",
        size_bytes=valid_pdf_path.stat().st_size,
        source_type=SourceType.API.value,
    )
    version = DocumentVersion(
        document=document,
        version_number=1,
        storage_bucket="local",
        storage_object_key=str(valid_pdf_path),
    )
    job = IngestionJob(
        document=document,
        job_type=JobType.INGEST.value,
        status=JobStatus.QUEUED.value,
    )
    db_session.add_all([document, version, job])
    db_session.commit()

    result = OCRService(db_session).process_job(job.id)

    artifacts = result.structured_json.get("page_artifacts")
    assert isinstance(artifacts, list)
    assert len(artifacts) == result.page_count
    assert artifacts[0]["page_number"] == 1
    assert artifacts[0]["backend"] == "fake"
    assert artifacts[0]["quality_flags"]
