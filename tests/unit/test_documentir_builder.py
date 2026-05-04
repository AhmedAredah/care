"""DocumentIR builder unit tests."""
from __future__ import annotations

from care.document_ir.builder import (
    build_document_ir_from_native_text,
    build_document_ir_from_ocr,
    build_document_ir_from_pages,
    build_native_page,
    build_ocr_page,
)
from care.ocr.providers.mock_ocr_provider import MockOCRProvider
from care.pdf.base import NativeTextWord


def test_build_from_ocr_assigns_provenance_and_ids() -> None:
    provider = MockOCRProvider()
    provider.load({})
    ocr_result = provider.process_page_image(image=None, page_context={})

    doc = build_document_ir_from_ocr(
        document_id="sha256-aaa",
        source_file_name="x.png",
        source_sha256="aaa",
        file_type="image",
        page_results=[(0, 800, 1000, ocr_result)],
    )

    assert doc.document_id == "sha256-aaa"
    assert doc.file_type == "image"
    assert doc.pages[0].text_source == "ocr"
    word = doc.pages[0].words[0]
    assert word.id == "p0_w00000"
    assert word.source == "mock_ocr"
    assert word.source_provider_type == "traditional_ocr"
    assert word.provenance is not None
    assert word.provenance.provider == "mock_ocr"
    assert word.can_map_to_image_coordinates is True


def test_build_from_native_text_marks_unmappable_to_image_coords() -> None:
    doc = build_document_ir_from_native_text(
        document_id="sha256-bbb",
        source_file_name="d.pdf",
        source_sha256="bbb",
        file_type="pdf",
        page_dimensions=[(595, 842)],
        page_word_lists=[["MOCK", "CRASH", "REPORT"]],
    )
    assert doc.pages[0].text_source == "native"
    word = doc.pages[0].words[0]
    assert word.source == "native_pdf"
    assert word.source_provider_type == "native_pdf"
    assert word.can_map_to_image_coordinates is False
    assert word.id == "p0_w00000"


def test_build_from_native_text_handles_empty_pages() -> None:
    doc = build_document_ir_from_native_text(
        document_id="sha256-ccc",
        source_file_name="d.pdf",
        source_sha256="ccc",
        file_type="pdf",
        page_dimensions=[(595, 842), (595, 842)],
        page_word_lists=[["A"], []],
    )
    assert len(doc.pages) == 2
    assert len(doc.pages[0].words) == 1
    assert doc.pages[1].words == []


def test_build_document_ir_from_pages_mixes_native_and_ocr() -> None:
    """The pipeline composes per-page Page objects (native or OCR)
    and wraps them in a DocumentIR. Pages must be sorted by index and
    both source kinds preserved."""
    provider = MockOCRProvider()
    provider.load({})
    ocr_result = provider.process_page_image(image=None, page_context={})

    page_native = build_native_page(
        page_index=0,
        width=800,
        height=1000,
        words=[NativeTextWord(page_index=0, text="HELLO", bbox=[0, 0, 50, 20])],
    )
    page_ocr = build_ocr_page(
        page_index=1,
        width=800,
        height=1000,
        result=ocr_result,
    )

    # Pass out of order to confirm the builder sorts.
    doc = build_document_ir_from_pages(
        document_id="sha256-mix",
        source_file_name="mixed.pdf",
        source_sha256="mix",
        file_type="pdf",
        pages=[page_ocr, page_native],
    )

    assert [p.page_index for p in doc.pages] == [0, 1]
    assert doc.pages[0].text_source == "native"
    assert doc.pages[1].text_source == "ocr"
    # Native page word carries pdf-native source markers; OCR page
    # carries the OCR provider's markers.
    assert doc.pages[0].words[0].source == "native_pdf"
    assert doc.pages[1].words[0].source_provider_type == "traditional_ocr"
    # Pipeline provenance is always present.
    assert any(p.provider == "care.pipeline" for p in doc.provenance)
