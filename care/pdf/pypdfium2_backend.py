"""pypdfium2-based PDF/image backend.

Inspects, text-layer-extracts, and renders both PDF and image inputs
locally using pypdfium2 + Pillow. No network access. No model files
required.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import cast

import pypdfium2 as pdfium
from PIL import Image

from ..ingestion.supported_files import is_image, is_pdf
from .base import (
    FileInspection,
    NativeTextResult,
    NativeTextWord,
    PDFImageBackend,
    RenderedPage,
)

_log = logging.getLogger(__name__)


class PypdfiumPDFImageBackend(PDFImageBackend):
    name = "pypdfium2"
    version = "5"
    provider_type = "pdf_image_backend"
    requires_network = False

    # ----- inspect ---------------------------------------------------------

    def inspect_file(self, file_path: Path) -> FileInspection:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(path)
        if is_image(path):
            return self._inspect_image(path)
        if is_pdf(path):
            return self._inspect_pdf(path)
        raise ValueError(f"Unsupported file type: {path}")

    def _inspect_image(self, path: Path) -> FileInspection:
        with Image.open(path) as img:
            img.load()
            width, height = img.size
        return FileInspection(
            file_type=path.suffix.lower().lstrip("."),
            page_count=1,
            page_dimensions=[(int(width), int(height))],
            has_text_layer=False,
            appears_image_only=True,
            requires_ocr=True,
            rotation=[0],
            page_has_text=[False],
        )

    def _inspect_pdf(self, path: Path) -> FileInspection:
        warnings: list[str] = []
        page_dimensions: list[tuple[int, int]] = []
        rotations: list[int] = []
        page_has_text: list[bool] = []

        doc = pdfium.PdfDocument(str(path))
        try:
            page_count = len(doc)
            for i in range(page_count):
                page = doc[i]
                try:
                    width = int(page.get_width())
                    height = int(page.get_height())
                    page_dimensions.append((width, height))
                    rotations.append(int(page.get_rotation()))
                    text_page = page.get_textpage()
                    try:
                        text = text_page.get_text_range()
                        page_has_text.append(bool(text and text.strip()))
                    finally:
                        text_page.close()
                finally:
                    page.close()
        finally:
            doc.close()

        has_any_text = any(page_has_text)
        appears_image_only = not has_any_text
        if appears_image_only:
            warnings.append("No text layer detected; OCR will be required.")
        elif not all(page_has_text):
            # Mixed: at least one native page and at least one image-only
            # page. Used to be silently mis-routed (whole doc went native
            # and image pages emitted nothing); per-page routing now
            # rasterizes the empty pages.
            empty = [i for i, has in enumerate(page_has_text) if not has]
            warnings.append(
                f"Mixed PDF — {len(empty)} of {page_count} pages have no text "
                f"layer; OCR will run on those pages."
            )
        return FileInspection(
            file_type="pdf",
            page_count=page_count,
            page_dimensions=page_dimensions,
            has_text_layer=has_any_text,
            appears_image_only=appears_image_only,
            requires_ocr=appears_image_only,
            rotation=rotations,
            warnings=warnings,
            page_has_text=page_has_text,
        )

    # ----- native text -----------------------------------------------------

    def extract_text_layer(
        self, file_path: Path, *, dpi: int = 200
    ) -> NativeTextResult:
        """Extract per-word native text and compute image-space bboxes.

        Word bboxes are returned in pixel coordinates of an image rendered
        at ``dpi`` (top-left origin), so they line up with whatever
        ``render_pages(..., dpi=dpi)`` produces. PDF's bottom-left
        coordinate space is converted internally.
        """
        path = Path(file_path)
        if not is_pdf(path):
            return NativeTextResult(has_text_layer=False, provider=self.name)

        scale = dpi / 72.0
        words: list[NativeTextWord] = []
        doc = pdfium.PdfDocument(str(path))
        try:
            for i in range(len(doc)):
                page = doc[i]
                try:
                    page_h_pt = page.get_height()
                    text_page = page.get_textpage()
                    try:
                        page_words = self._words_from_textpage(
                            text_page, i, page_h_pt, scale
                        )
                    finally:
                        text_page.close()
                finally:
                    page.close()
                words.extend(page_words)
        finally:
            doc.close()

        return NativeTextResult(
            words=words, has_text_layer=bool(words), provider=self.name
        )

    @staticmethod
    def _words_from_textpage(
        text_page,
        page_index: int,
        page_h_pt: float,
        scale: float,
    ) -> list[NativeTextWord]:
        n = text_page.count_chars()
        if n <= 0:
            return []

        words: list[NativeTextWord] = []
        current_chars: list[str] = []
        current_bbox: list[float] | None = None  # [left, bottom, right, top] in PDF pts

        for j in range(n):
            ch = text_page.get_text_range(j, 1)
            if not ch:
                continue
            if ch.isspace():
                if current_chars:
                    words.append(
                        PypdfiumPDFImageBackend._finalize_word(
                            current_chars, current_bbox, page_index, page_h_pt, scale
                        )
                    )
                    current_chars = []
                    current_bbox = None
                continue
            try:
                char_box = text_page.get_charbox(j)
            except Exception:
                char_box = None
            current_chars.append(ch)
            if char_box is not None:
                if current_bbox is None:
                    current_bbox = [
                        float(char_box[0]),
                        float(char_box[1]),
                        float(char_box[2]),
                        float(char_box[3]),
                    ]
                else:
                    current_bbox[0] = min(current_bbox[0], float(char_box[0]))
                    current_bbox[1] = min(current_bbox[1], float(char_box[1]))
                    current_bbox[2] = max(current_bbox[2], float(char_box[2]))
                    current_bbox[3] = max(current_bbox[3], float(char_box[3]))

        if current_chars:
            words.append(
                PypdfiumPDFImageBackend._finalize_word(
                    current_chars, current_bbox, page_index, page_h_pt, scale
                )
            )
        return words

    @staticmethod
    def _finalize_word(
        chars: list[str],
        bbox_pt: list[float] | None,
        page_index: int,
        page_h_pt: float,
        scale: float,
    ) -> NativeTextWord:
        text = "".join(chars)
        if bbox_pt is None:
            return NativeTextWord(page_index=page_index, text=text, bbox=None)
        left, bottom, right, top = bbox_pt
        return NativeTextWord(
            page_index=page_index,
            text=text,
            bbox=[
                left * scale,
                (page_h_pt - top) * scale,
                right * scale,
                (page_h_pt - bottom) * scale,
            ],
        )

    # ----- render ----------------------------------------------------------

    def render_pages(
        self,
        file_path: Path,
        output_dir: Path,
        dpi: int = 200,
        page_indices: list[int] | None = None,
    ) -> list[RenderedPage]:
        path = Path(file_path)
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        if is_image(path):
            # Single-page sources ignore page_indices — page 0 is the only
            # legal index, and asking for nothing returns nothing.
            if page_indices is not None and 0 not in page_indices:
                return []
            return self._render_image(path, out, dpi)
        if is_pdf(path):
            return self._render_pdf(path, out, dpi, page_indices)
        raise ValueError(f"Unsupported file type: {path}")

    def _render_image(self, path: Path, out: Path, dpi: int) -> list[RenderedPage]:
        # For image inputs, treat the source itself as page 0. We re-save as
        # PNG so downstream OCR has a stable file format.
        with Image.open(path) as img:
            img = img.convert("RGB") if img.mode not in ("RGB", "RGBA", "L") else img
            target = out / "page_0.png"
            img.save(target, format="PNG")
            return [
                RenderedPage(
                    page_index=0,
                    image_path=target,
                    width=int(img.width),
                    height=int(img.height),
                    dpi=dpi,
                )
            ]

    def _render_pdf(
        self,
        path: Path,
        out: Path,
        dpi: int,
        page_indices: list[int] | None,
    ) -> list[RenderedPage]:
        rendered: list[RenderedPage] = []
        scale = dpi / 72.0
        doc = pdfium.PdfDocument(str(path))
        try:
            wanted = (
                set(page_indices)
                if page_indices is not None
                else set(range(len(doc)))
            )
            for i in range(len(doc)):
                if i not in wanted:
                    continue
                page = doc[i]
                try:
                    bitmap = page.render(scale=scale)
                    pil = bitmap.to_pil()
                    target = out / f"page_{i}.png"
                    pil.save(target, format="PNG")
                    rendered.append(
                        RenderedPage(
                            page_index=i,
                            image_path=target,
                            width=int(pil.width),
                            height=int(pil.height),
                            dpi=dpi,
                        )
                    )
                finally:
                    page.close()
        finally:
            doc.close()
        return rendered
