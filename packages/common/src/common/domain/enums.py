from enum import StrEnum


class SourceType(StrEnum):
    API = "api"
    CLI = "cli"


class JobType(StrEnum):
    INGEST = "ingest"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class OCRStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AssetType(StrEnum):
    ORIGINAL_PDF = "original_pdf"
    OCR_JSON = "ocr_json"
    OCR_REFINEMENT_JSON = "ocr_refinement_json"
    MARKDOWN = "markdown"
    TEXT = "text"
    PREFLIGHT_JSON = "preflight_json"
