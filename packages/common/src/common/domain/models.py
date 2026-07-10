from typing import Any, Literal

from pydantic import BaseModel, Field


class BoundingBoxModel(BaseModel):
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None


class TableModel(BaseModel):
    id: str
    page_number: int
    caption: str | None = None
    bbox: BoundingBoxModel | None = None
    cells: list[dict[str, Any]] = Field(default_factory=list)


class FigureModel(BaseModel):
    id: str
    page_number: int
    caption: str | None = None
    bbox: BoundingBoxModel | None = None


class BlockModel(BaseModel):
    id: str
    page_number: int
    block_type: str
    reading_order: int
    text: str | None = None
    bbox: BoundingBoxModel | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageModel(BaseModel):
    page_number: int
    width: float | None = None
    height: float | None = None
    blocks: list[BlockModel] = Field(default_factory=list)
    tables: list[TableModel] = Field(default_factory=list)
    figures: list[FigureModel] = Field(default_factory=list)


class PageArtifactModel(BaseModel):
    page_number: int
    text: str = ""
    markdown: str = ""
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    figures: list[dict[str, Any]] = Field(default_factory=list)
    width: float | None = None
    height: float | None = None
    text_origin: Literal["native", "ocr", "hybrid", "unknown", "failed"] = "unknown"
    page_class: Literal["native", "scan", "hybrid", "low_quality", "failed", "unknown"] = "unknown"
    backend: str | None = None
    backend_version: str | None = None
    rotation_applied: int | None = None
    page_order_reversed: bool = False
    confidence: float | None = None
    quality_flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OCRResultModel(BaseModel):
    engine_name: str
    engine_version: str
    pipeline_version: str
    full_text: str
    markdown_text: str
    structured_json: dict[str, Any]
    page_count: int
    confidence_summary: dict[str, Any] | None = None
    refinement_payload: dict[str, Any] | None = None


class DocumentModel(BaseModel):
    document_id: str
    version_id: str
    original_filename: str
    mime_type: str
    sha256: str
    size_bytes: int
    source_type: str
