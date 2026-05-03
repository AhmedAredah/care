"""PDF / image backend interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FileInspection:
    file_type: str  # "pdf", "png", "jpg", "jpeg", "tif", "tiff"
    page_count: int
    page_dimensions: list[tuple[int, int]]
    has_text_layer: bool
    appears_image_only: bool
    requires_ocr: bool
    rotation: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RenderedPage:
    page_index: int
    image_path: Path
    width: int
    height: int
    dpi: int


@dataclass
class NativeTextWord:
    page_index: int
    text: str
    bbox: Optional[list[float]] = None


@dataclass
class NativeTextResult:
    words: list[NativeTextWord] = field(default_factory=list)
    has_text_layer: bool = False
    provider: str = ""


class PDFImageBackend(ABC):
    name: str = ""
    version: str = ""
    provider_type: str = "pdf_image_backend"
    requires_network: bool = False

    @abstractmethod
    def inspect_file(self, file_path: Path) -> FileInspection: ...

    @abstractmethod
    def extract_text_layer(self, file_path: Path) -> NativeTextResult: ...

    @abstractmethod
    def render_pages(
        self, file_path: Path, output_dir: Path, dpi: int = 200
    ) -> list[RenderedPage]: ...
