from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="megadoc", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8080, alias="APP_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    max_upload_size_bytes: int = Field(default=50 * 1024 * 1024, alias="MAX_UPLOAD_SIZE_BYTES")
    deduplicate_by_hash: bool = Field(default=True, alias="DEDUPLICATE_BY_HASH")
    database_url: str = Field(
        default="postgresql+psycopg://megadoc:megadoc@postgres:5432/megadoc", alias="DATABASE_URL"
    )
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://redis:6379/1", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(
        default="redis://redis:6379/2", alias="CELERY_RESULT_BACKEND"
    )
    celery_task_always_eager: bool = Field(default=False, alias="CELERY_TASK_ALWAYS_EAGER")
    ingestion_queue_default: str = Field(default="ingestion", alias="INGESTION_QUEUE_DEFAULT")
    ingestion_queue_llm_vision: str = Field(
        default="ingestion_llm_vision",
        alias="INGESTION_QUEUE_LLM_VISION",
    )
    ingestion_job_running_timeout_seconds: int = Field(
        default=6 * 60 * 60,
        alias="INGESTION_JOB_RUNNING_TIMEOUT_SECONDS",
    )
    ingestion_job_queued_timeout_seconds: int = Field(
        default=24 * 60 * 60,
        alias="INGESTION_JOB_QUEUED_TIMEOUT_SECONDS",
    )
    s3_endpoint_url: str = Field(default="http://minio:9000", alias="S3_ENDPOINT_URL")
    s3_access_key: str = Field(default="minioadmin", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="minioadmin", alias="S3_SECRET_KEY")
    s3_bucket_raw: str = Field(default="raw-documents", alias="S3_BUCKET_RAW")
    s3_bucket_derivatives: str = Field(default="derived-documents", alias="S3_BUCKET_DERIVATIVES")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")
    storage_backend: str = Field(default="s3", alias="STORAGE_BACKEND")
    local_storage_path: Path = Field(default=Path("/tmp/megadoc-storage"), alias="LOCAL_STORAGE_PATH")
    ocr_backend: str = Field(default="docling", alias="OCR_BACKEND")
    ocr_accelerator_device: str = Field(default="auto", alias="OCR_ACCELERATOR_DEVICE")
    ocr_accelerator_num_threads: int = Field(default=4, alias="OCR_ACCELERATOR_NUM_THREADS")
    ocr_rapidocr_backend: str = Field(default="torch", alias="OCR_RAPIDOCR_BACKEND")
    ocr_llm_vision_endpoint: str = Field(
        default="http://10.89.0.3:8080/v1",
        alias="OCR_LLM_VISION_ENDPOINT",
    )
    ocr_llm_vision_model: str = Field(default="qwen3.6-A3B", alias="OCR_LLM_VISION_MODEL")
    ocr_llm_vision_api_key: str | None = Field(default=None, alias="OCR_LLM_VISION_API_KEY")
    ocr_llm_vision_timeout: int = Field(default=240, alias="OCR_LLM_VISION_TIMEOUT")
    ocr_llm_vision_max_tokens: int = Field(default=4096, alias="OCR_LLM_VISION_MAX_TOKENS")
    ocr_llm_vision_render_scale: float = Field(default=1.5, alias="OCR_LLM_VISION_RENDER_SCALE")
    ocr_dots_native_endpoint: str = Field(
        default="http://10.89.0.3:8080/v1",
        alias="OCR_DOTS_NATIVE_ENDPOINT",
    )
    ocr_dots_native_model: str = Field(
        default="ggml-org/dots.ocr-GGUF:Q8_0",
        alias="OCR_DOTS_NATIVE_MODEL",
    )
    ocr_dots_native_api_key: str | None = Field(default=None, alias="OCR_DOTS_NATIVE_API_KEY")
    ocr_dots_native_timeout: int = Field(default=240, alias="OCR_DOTS_NATIVE_TIMEOUT")
    ocr_dots_native_render_scale: float = Field(default=1.5, alias="OCR_DOTS_NATIVE_RENDER_SCALE")
    ocr_dots_native_fallback_render_scale: float = Field(
        default=2.0,
        alias="OCR_DOTS_NATIVE_FALLBACK_RENDER_SCALE",
    )
    ocr_dots_native_layout_max_tokens: int = Field(default=8192, alias="OCR_DOTS_NATIVE_LAYOUT_MAX_TOKENS")
    ocr_dots_native_ocr_max_tokens: int = Field(default=4096, alias="OCR_DOTS_NATIVE_OCR_MAX_TOKENS")
    ocr_dots_native_request_retries: int = Field(default=2, alias="OCR_DOTS_NATIVE_REQUEST_RETRIES")
    pipeline_version: str = Field(default="v1", alias="PIPELINE_VERSION")
    request_timeout_seconds: int = Field(default=30, alias="REQUEST_TIMEOUT_SECONDS")
    api_base_url: str = Field(default="http://api:8080", alias="API_BASE_URL")
    preflight_enabled: bool = Field(default=True, alias="PREFLIGHT_ENABLED")
    preflight_text_sample_pages: int = Field(default=4, alias="PREFLIGHT_TEXT_SAMPLE_PAGES")
    preflight_heavy_scan_bytes_per_page: int = Field(
        default=400_000,
        alias="PREFLIGHT_HEAVY_SCAN_BYTES_PER_PAGE",
    )
    rotation_detector_backend: str = Field(default="none", alias="ROTATION_DETECTOR_BACKEND")
    rotation_detector_model_id: str | None = Field(default=None, alias="ROTATION_DETECTOR_MODEL_ID")
    rotation_detector_min_confidence: float = Field(
        default=0.80,
        alias="ROTATION_DETECTOR_MIN_CONFIDENCE",
    )
    rotation_detector_sample_pages: int = Field(
        default=4,
        alias="ROTATION_DETECTOR_SAMPLE_PAGES",
    )
    rotation_detector_min_consensus: float = Field(
        default=0.75,
        alias="ROTATION_DETECTOR_MIN_CONSENSUS",
    )
    ocr_refinement_enabled: bool = Field(default=False, alias="OCR_REFINEMENT_ENABLED")
    ocr_refinement_endpoint: str = Field(
        default="http://10.89.0.3:8080/v1",
        alias="OCR_REFINEMENT_ENDPOINT",
    )
    ocr_refinement_model: str = Field(default="qwen3.6-A3B", alias="OCR_REFINEMENT_MODEL")
    ocr_refinement_api_key: str | None = Field(default=None, alias="OCR_REFINEMENT_API_KEY")
    ocr_refinement_timeout: int = Field(default=180, alias="OCR_REFINEMENT_TIMEOUT")
    ocr_refinement_max_tokens: int = Field(default=2048, alias="OCR_REFINEMENT_MAX_TOKENS")
    ocr_refinement_max_pages: int = Field(default=3, alias="OCR_REFINEMENT_MAX_PAGES")
    ocr_refinement_min_page_score: float = Field(
        default=0.35,
        alias="OCR_REFINEMENT_MIN_PAGE_SCORE",
    )
    ocr_refinement_promote_text: bool = Field(default=False, alias="OCR_REFINEMENT_PROMOTE_TEXT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
