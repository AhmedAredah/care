"""bbox_mapper — text offsets ↔ word bboxes."""
from __future__ import annotations

from care.document_ir import Page, Word
from care.pii.entities import PIIEntity
from care.redaction import (
    attach_bbox_to_pii_entities,
    derive_bbox_from_words,
    map_text_offset_to_words,
    page_word_offsets,
)


def _page_with_word_bboxes() -> Page:
    """Three words with bboxes laid out left-to-right at row y=0."""
    words = []
    for i, t in enumerate(["alpha", "beta", "gamma"]):
        words.append(
            Word(
                id=f"p0_w{i}",
                text=t,
                bbox=[i * 60, 0, i * 60 + 50, 20],
                source="mock",
                source_provider_type="traditional_ocr",
                can_map_to_image_coordinates=True,
            )
        )
    return Page(page_index=0, width=300, height=50, words=words)


def test_page_word_offsets_returns_join_offsets() -> None:
    page = _page_with_word_bboxes()
    offsets = page_word_offsets(page)
    assert [(s, e, w.text) for s, e, w in offsets] == [
        (0, 5, "alpha"),
        (6, 10, "beta"),
        (11, 16, "gamma"),
    ]


def test_map_text_offset_to_words_single_word() -> None:
    page = _page_with_word_bboxes()
    overlapping = map_text_offset_to_words(page, 6, 10)
    assert [w.text for w in overlapping] == ["beta"]


def test_map_text_offset_to_words_multi_word_span() -> None:
    page = _page_with_word_bboxes()
    overlapping = map_text_offset_to_words(page, 0, 10)
    assert [w.text for w in overlapping] == ["alpha", "beta"]


def test_derive_bbox_from_words_returns_min_max() -> None:
    page = _page_with_word_bboxes()
    bbox = derive_bbox_from_words(page.words)
    assert bbox == [0, 0, 170, 20]


def test_derive_bbox_returns_none_when_no_word_has_bbox() -> None:
    page = Page(
        page_index=0,
        width=100,
        height=100,
        words=[
            Word(id="w0", text="x", source="native_pdf", source_provider_type="native_pdf"),
        ],
    )
    assert derive_bbox_from_words(page.words) is None


def test_attach_bbox_marks_unmapped_when_no_word_has_bbox() -> None:
    page = Page(
        page_index=0,
        width=100,
        height=100,
        words=[
            Word(id="w0", text="alpha", source="native_pdf", source_provider_type="native_pdf"),
        ],
    )
    e = PIIEntity(
        entity_type="VIN",
        text="alpha",
        start_offset=0,
        end_offset=5,
        provider="regex",
        sources=["regex"],
    )
    attach_bbox_to_pii_entities(page, [e])
    assert e.bbox is None
    assert e.can_map_to_image_coordinates is False
    assert e.requires_review is True


def test_attach_bbox_attaches_when_words_have_bboxes() -> None:
    page = _page_with_word_bboxes()
    e = PIIEntity(
        entity_type="VIN",
        text="beta",
        start_offset=6,
        end_offset=10,
        provider="regex",
        sources=["regex"],
    )
    attach_bbox_to_pii_entities(page, [e])
    assert e.bbox == [60, 0, 110, 20]
    assert e.can_map_to_image_coordinates is True
    assert e.requires_review is False
