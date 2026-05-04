"""OCR result dataclasses (provider-side; converted into DocumentIR by the pipeline)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OCRWord:
    text: str
    bbox: list[float] | None = None
    confidence: float | None = None


@dataclass
class OCRLine:
    text: str
    bbox: list[float] | None = None
    confidence: float | None = None
    word_indices: list[int] = field(default_factory=list)


@dataclass
class OCRBlock:
    text: str
    bbox: list[float] | None = None
    line_indices: list[int] = field(default_factory=list)


@dataclass
class OCRResult:
    words: list[OCRWord] = field(default_factory=list)
    lines: list[OCRLine] = field(default_factory=list)
    blocks: list[OCRBlock] = field(default_factory=list)
    confidence: float | None = None
    provider_name: str = ""
    provider_version: str = ""
    warnings: list[str] = field(default_factory=list)
    can_map_to_image_coordinates: bool = False
