"""DocumentIR builder unit tests."""
from __future__ import annotations

from care.document_ir.builder import (
    build_document_ir_from_native_text,
    build_document_ir_from_ocr,
)
from care.ocr.providers.mock_ocr_provider import MockOCRProvider


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
