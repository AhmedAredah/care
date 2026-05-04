"""Provider-neutral DocumentIR models.

All OCR providers, PDF text-layer extractors, and VLM/document-AI
providers must convert their outputs into these structures so that the
rest of the pipeline never depends on a specific provider.


"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AlternativeSource(BaseModel):
    provider: str
    text: str
    confidence: float | None = None
    bbox: list[float] | None = None


class Provenance(BaseModel):
    provider: str
    provider_version: str = "unknown"
    provider_type: str = "unknown"
    notes: str | None = None


class Word(BaseModel):
    id: str
    text: str
    bbox: list[float] | None = None
    confidence: float | None = None
    source: str
    source_provider_type: str
    source_provider_version: str = "unknown"
    alternative_sources: list[AlternativeSource] = Field(default_factory=list)
    provenance: Provenance | None = None
    can_map_to_image_coordinates: bool = False


class Line(BaseModel):
    id: str
    text: str = ""
    bbox: list[float] | None = None
    word_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None
    source: str = "unknown"


class Block(BaseModel):
    id: str
    text: str = ""
    bbox: list[float] | None = None
    line_ids: list[str] = Field(default_factory=list)
    role: str | None = None
    source: str = "unknown"


class Region(BaseModel):
    id: str
    label: str
    bbox: list[float] | None = None
    confidence: float | None = None
    requires_review: bool = False
    source: str = "unknown"


class Warning(BaseModel):
    code: str
    message: str
    page_index: int | None = None


class Page(BaseModel):
    page_index: int
    width: int
    height: int
    rotation: int = 0
    text_source: str = "unknown"
    rendered_image_path: str | None = None
    blocks: list[Block] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)
    regions: list[Region] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)


class DocumentIR(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    source_file_name: str
    source_sha256: str
    file_type: str
    created_at: str
    pages: list[Page] = Field(default_factory=list)
    provenance: list[Provenance] = Field(default_factory=list)
    extraction_warnings: list[Warning] = Field(default_factory=list)
