from common.config import Settings
from common.application.knowledge import (
    ensure_scan_unit_for_ocr_result,
    get_dispatchable_knowledge_scan_unit_ids,
    mark_knowledge_job_pending_dispatch,
)
from common.db.models import Document, DocumentVersion, KnowledgeJob, OCRResult
from api.main import _ingestion_queue_for_backend


def test_ingestion_queue_defaults_to_standard_queue() -> None:
    settings = Settings()
    assert _ingestion_queue_for_backend(settings, None) == settings.ingestion_queue_default
    assert _ingestion_queue_for_backend(settings, "docling") == settings.ingestion_queue_default


def test_ingestion_queue_uses_llm_vision_queue() -> None:
    settings = Settings()
    assert _ingestion_queue_for_backend(settings, "llm_vision") == settings.ingestion_queue_llm_vision
    assert _ingestion_queue_for_backend(settings, "dots_native") == settings.ingestion_queue_llm_vision


def _ocr_result(db_session) -> OCRResult:
    document = Document(
        original_filename="sample.pdf",
        mime_type="application/pdf",
        sha256="0" * 64,
        size_bytes=10,
        source_type="upload",
    )
    db_session.add(document)
    db_session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        storage_bucket="documents",
        storage_object_key="sample.pdf",
    )
    db_session.add(version)
    db_session.flush()
    ocr_result = OCRResult(
        document_id=document.id,
        document_version_id=version.id,
        engine_name="fake",
        engine_version="test",
        pipeline_version="test",
        status="succeeded",
        full_text="text",
        markdown_text="text",
        structured_json={},
        page_count=1,
    )
    db_session.add(ocr_result)
    db_session.flush()
    return ocr_result


def test_knowledge_dispatch_ignores_topic_finalization_jobs(db_session) -> None:
    scan_unit, full_job, _, _ = ensure_scan_unit_for_ocr_result(db_session, _ocr_result(db_session))
    full_job.status = "succeeded"
    db_session.add(KnowledgeJob(scan_unit_id=scan_unit.id, job_type="topic_finalization", status="queued"))
    db_session.commit()

    assert get_dispatchable_knowledge_scan_unit_ids(db_session) == []
    assert mark_knowledge_job_pending_dispatch(db_session, scan_unit.id) is False


def test_ensure_scan_unit_requeues_latest_full_processing_job_only(db_session) -> None:
    ocr_result = _ocr_result(db_session)
    scan_unit, full_job, _, _ = ensure_scan_unit_for_ocr_result(db_session, ocr_result)
    full_job.status = "failed"
    db_session.add(KnowledgeJob(scan_unit_id=scan_unit.id, job_type="topic_finalization", status="succeeded"))
    db_session.commit()

    _, knowledge_job, _, should_dispatch = ensure_scan_unit_for_ocr_result(db_session, ocr_result)

    assert should_dispatch is True
    assert knowledge_job.job_type == "full_processing"
    assert knowledge_job.status == "queued"
