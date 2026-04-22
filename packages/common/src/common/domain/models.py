from typing import Any

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


class OCRResultModel(BaseModel):
    engine_name: str
    engine_version: str
    pipeline_version: str
    full_text: str
    markdown_text: str
    structured_json: dict[str, Any]
    page_count: int
    confidence_summary: dict[str, Any] | None = None


class DocumentModel(BaseModel):
    document_id: str
    version_id: str
    original_filename: str
    mime_type: str
    sha256: str
    size_bytes: int
    source_type: str

