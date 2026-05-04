"""pypdfium2-backed PDF/image backend tests."""
from __future__ import annotations

from pathlib import Path

from care.pdf import (
    FileInspection,
    NativeTextResult,
    RenderedPage,
)
from care.pdf.pypdfium2_backend import PypdfiumPDFImageBackend
from tests._fixtures import (
    make_digital_pdf,
    make_image_only_pdf,
    make_mixed_pdf,
    make_synthetic_image,
)


def test_inspect_image_marks_ocr_required(tmp_path: Path) -> None:
    p = make_synthetic_image(tmp_path / "scan.png")
    backend = PypdfiumPDFImageBackend()
    inspection = backend.inspect_file(p)
    assert isinstance(inspection, FileInspection)
    assert inspection.file_type == "png"
    assert inspection.page_count == 1
    assert inspection.has_text_layer is False
    assert inspection.appears_image_only is True
    assert inspection.requires_ocr is True
    assert len(inspection.page_dimensions) == 1
    assert inspection.page_has_text == [False]


def test_inspect_digital_pdf_finds_text_layer(tmp_path: Path) -> None:
    p = make_digital_pdf(tmp_path / "digital.pdf")
    backend = PypdfiumPDFImageBackend()
    inspection = backend.inspect_file(p)
    assert inspection.file_type == "pdf"
    assert inspection.page_count >= 1
    assert inspection.has_text_layer is True
    assert inspection.requires_ocr is False
    assert inspection.page_has_text and all(inspection.page_has_text)


def test_inspect_image_only_pdf_requires_ocr(tmp_path: Path) -> None:
    img = make_synthetic_image(tmp_path / "scan.png")
    pdf = make_image_only_pdf(tmp_path / "scanned.pdf", image_path=img)
    backend = PypdfiumPDFImageBackend()
    inspection = backend.inspect_file(pdf)
    assert inspection.file_type == "pdf"
    assert inspection.has_text_layer is False
    assert inspection.requires_ocr is True
    assert inspection.page_has_text == [False]


def test_inspect_mixed_pdf_records_per_page_text_presence(tmp_path: Path) -> None:
    """A PDF with one native page and one image-only page must report
    page_has_text=[True, False] and warn about the mixed shape, while
    document-level flags stay monolithic for back-compat."""
    img = make_synthetic_image(tmp_path / "scratch.png")
    pdf = make_mixed_pdf(tmp_path / "mixed.pdf", image_path=img)

    backend = PypdfiumPDFImageBackend()
    inspection = backend.inspect_file(pdf)

    assert inspection.page_count == 2
    assert inspection.page_has_text == [True, False]
    # has_text_layer is "any page has text", so True here.
    assert inspection.has_text_layer is True
    # appears_image_only / requires_ocr are "every page is image-only",
    # so False — but the warnings list flags the mixed shape so callers
    # who don't read page_has_text still get a hint.
    assert inspection.appears_image_only is False
    assert inspection.requires_ocr is False
    assert any("Mixed PDF" in w for w in inspection.warnings)


def test_extract_text_layer_returns_words(tmp_path: Path) -> None:
    p = make_digital_pdf(
        tmp_path / "d.pdf",
        lines=["MOCK CRASH REPORT", "Officer Synthetic Test"],
    )
    backend = PypdfiumPDFImageBackend()
    native = backend.extract_text_layer(p)
    assert isinstance(native, NativeTextResult)
    assert native.has_text_layer is True
    assert any(w.text == "MOCK" for w in native.words)
    assert any(w.text == "REPORT" for w in native.words)


def test_extract_text_layer_on_image_returns_empty(tmp_path: Path) -> None:
    p = make_synthetic_image(tmp_path / "scan.png")
    backend = PypdfiumPDFImageBackend()
    native = backend.extract_text_layer(p)
    assert native.has_text_layer is False
    assert native.words == []


def test_render_image_passes_through(tmp_path: Path) -> None:
    p = make_synthetic_image(tmp_path / "scan.png", size=(640, 480))
    out = tmp_path / "work"
    backend = PypdfiumPDFImageBackend()
    pages = backend.render_pages(p, out, dpi=200)
    assert len(pages) == 1
    assert isinstance(pages[0], RenderedPage)
    assert pages[0].image_path.exists()
    assert pages[0].width == 640
    assert pages[0].height == 480


def test_render_pdf_emits_one_image_per_page(tmp_path: Path) -> None:
    p = make_digital_pdf(tmp_path / "d.pdf")
    out = tmp_path / "work"
    backend = PypdfiumPDFImageBackend()
    pages = backend.render_pages(p, out, dpi=144)
    assert len(pages) >= 1
    for r in pages:
        assert r.image_path.exists()
        assert r.image_path.suffix == ".png"
        assert r.dpi == 144


def test_render_pdf_filters_to_requested_page_indices(tmp_path: Path) -> None:
    """``page_indices`` lets the caller render a subset — used by the
    mixed-PDF path so we don't rasterize pages whose text we already
    extracted natively."""
    img = make_synthetic_image(tmp_path / "scratch.png")
    p = make_mixed_pdf(tmp_path / "mixed.pdf", image_path=img)
    out = tmp_path / "work"
    backend = PypdfiumPDFImageBackend()

    pages = backend.render_pages(p, out, dpi=100, page_indices=[1])
    assert [r.page_index for r in pages] == [1]
    assert pages[0].image_path.exists()
    # Page 0 was NOT rendered.
    assert not (out / "page_0.png").exists()


# ---- Phase 5: image-space char/word bboxes ----------------------------------


def test_extract_text_layer_returns_image_space_bboxes(tmp_path: Path) -> None:
    """Phase 5: every native word that has a charbox returns a 4-tuple bbox in
    pixel coordinates of an image rendered at the same dpi (top-left origin)."""
    p = make_digital_pdf(
        tmp_path / "d.pdf",
        lines=["MOCK CRASH REPORT", "Officer Synthetic Test"],
    )
    backend = PypdfiumPDFImageBackend()
    native = backend.extract_text_layer(p, dpi=200)
    assert native.has_text_layer is True
    assert any(w.bbox is not None for w in native.words)
    for w in native.words:
        if w.bbox is None:
            continue
        x0, y0, x1, y1 = w.bbox
        assert x1 > x0, f"non-positive width for word {w.text!r}: {w.bbox}"
        assert y1 > y0, f"non-positive height for word {w.text!r}: {w.bbox}"
        # All coordinates are non-negative pixel values.
        assert x0 >= 0 and y0 >= 0


def test_extract_text_layer_bboxes_match_render_dpi(tmp_path: Path) -> None:
    """Word bboxes at dpi=200 must lie inside the rendered page image at
    dpi=200 — confirming the PDF→image coordinate conversion is correct."""
    p = make_digital_pdf(tmp_path / "d.pdf", lines=["HELLO WORLD"])
    out = tmp_path / "work"
    backend = PypdfiumPDFImageBackend()
    rendered = backend.render_pages(p, out, dpi=200)
    native = backend.extract_text_layer(p, dpi=200)
    assert len(rendered) == 1
    page_w, page_h = rendered[0].width, rendered[0].height
    for w in native.words:
        if w.bbox is None:
            continue
        x0, y0, x1, y1 = w.bbox
        # Allow tiny float rounding overflow at the edge.
        assert x0 >= -1 and y0 >= -1
        assert x1 <= page_w + 1, f"{w.text!r} bbox x1={x1} > page_w={page_w}"
        assert y1 <= page_h + 1, f"{w.text!r} bbox y1={y1} > page_h={page_h}"


def test_extract_text_layer_dpi_scales_bboxes(tmp_path: Path) -> None:
    """Doubling dpi must (approximately) double bbox coordinates."""
    p = make_digital_pdf(tmp_path / "d.pdf", lines=["HELLO"])
    backend = PypdfiumPDFImageBackend()
    low = backend.extract_text_layer(p, dpi=72)
    high = backend.extract_text_layer(p, dpi=144)
    low_words = [w for w in low.words if w.bbox is not None]
    high_words = [w for w in high.words if w.bbox is not None]
    assert low_words and high_words
    # Same word count, paired in order.
    assert len(low_words) == len(high_words)
    for lo, hi in zip(low_words, high_words):
        for li, hi_v in zip(lo.bbox, hi.bbox):
            # Tolerate rounding — should be roughly 2× since 144/72 = 2.
            if li == 0:
                continue
            ratio = hi_v / li
            assert 1.8 <= ratio <= 2.2, f"unexpected scale ratio {ratio} for {lo.text!r}"
