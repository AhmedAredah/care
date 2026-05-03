"""OCR result dataclasses (provider-side; converted into DocumentIR by the pipeline)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class OCRWord:
    text: str
    bbox: Optional[list[float]] = None
    confidence: Optional[float] = None


@dataclass
class OCRLine:
    text: str
    bbox: Optional[list[float]] = None
    confidence: Optional[float] = None
    word_indices: list[int] = field(default_factory=list)


@dataclass
class OCRBlock:
    text: str
    bbox: Optional[list[float]] = None
    line_indices: list[int] = field(default_factory=list)


@dataclass
class OCRResult:
    words: list[OCRWord] = field(default_factory=list)
    lines: list[OCRLine] = field(default_factory=list)
    blocks: list[OCRBlock] = field(default_factory=list)
    confidence: Optional[float] = None
    provider_name: str = ""
    provider_version: str = ""
    warnings: list[str] = field(default_factory=list)
    can_map_to_image_coordinates: bool = False
