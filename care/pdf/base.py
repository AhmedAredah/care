"""PDF / image backend interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


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
    # Per-page native-text presence. Length must match ``page_count`` when
    # populated; empty means "not measured" (legacy callers). The pipeline
    # uses this to route mixed PDFs page-by-page — pages with native text
    # bypass OCR while image-only pages in the same document still get
    # rasterized and OCR'd. Document-level flags above stay monolithic
    # (``has_text_layer = any(page_has_text)``,
    # ``appears_image_only = not any(page_has_text)``,
    # ``requires_ocr = not any(page_has_text)``) for back-compat with
    # existing callers; rely on this list when per-page routing matters.
    page_has_text: list[bool] = field(default_factory=list)


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
    bbox: list[float] | None = None
    # Native PDF text comes from the document author's own text layer
    # (pypdfium2's textpage), so it is treated as ground-truth and
    # carries confidence=1.0 by convention. Downstream code that
    # filters on a low-confidence threshold (the QA gate's
    # ``require_review_for_low_ocr_confidence``) therefore reasons
    # uniformly across native and OCR pages instead of skipping
    # native pages entirely. Override at call-sites only when a
    # provider actually computes a calibrated value.
    confidence: float = 1.0


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
        self,
        file_path: Path,
        output_dir: Path,
        dpi: int = 200,
        page_indices: list[int] | None = None,
    ) -> list[RenderedPage]: ...
