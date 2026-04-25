from common.config import Settings
from api.main import _ingestion_queue_for_backend


def test_ingestion_queue_defaults_to_standard_queue() -> None:
    settings = Settings()
    assert _ingestion_queue_for_backend(settings, None) == settings.ingestion_queue_default
    assert _ingestion_queue_for_backend(settings, "docling") == settings.ingestion_queue_default


def test_ingestion_queue_uses_llm_vision_queue() -> None:
    settings = Settings()
    assert _ingestion_queue_for_backend(settings, "llm_vision") == settings.ingestion_queue_llm_vision
    assert _ingestion_queue_for_backend(settings, "dots_native") == settings.ingestion_queue_llm_vision
