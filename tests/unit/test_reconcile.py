"""DocumentIR reconciliation tests (Phase 5 — GOVERNANCE.md §OCR / VLM Reconciliation)."""
from __future__ import annotations

from care.document_ir.models import (
    DocumentIR,
    Page,
    Provenance,
    Word,
)
from care.document_ir.reconcile import (
    AlternativeSourceDoc,
    reconcile_with_alternatives,
)


def _word(
    *,
    id: str,
    text: str,
    bbox: list[float] | None,
    source: str = "native_pdf",
    source_provider_type: str = "native_pdf",
) -> Word:
    return Word(
        id=id,
        text=text,
        bbox=bbox,
        source=source,
        source_provider_type=source_provider_type,
        source_provider_version="0.0.0",
        provenance=Provenance(
            provider=source, provider_version="0", provider_type=source_provider_type
        ),
        can_map_to_image_coordinates=bbox is not None,
    )


def _doc(words: list[Word], *, page_index: int = 0, text_source: str = "native") -> DocumentIR:
    return DocumentIR(
        document_id="t",
        source_file_name="t.pdf",
        source_sha256="0" * 64,
        file_type="pdf",
        created_at="now",
        pages=[
            Page(
                page_index=page_index,
                width=1000,
                height=1000,
                text_source=text_source,
                words=words,
            )
        ],
    )


def test_reconcile_merges_overlapping_alt_into_base_word() -> None:
    base = _doc([
        _word(id="b0", text="Hello", bbox=[10, 10, 50, 30]),
    ])
    alt = _doc(
        [_word(id="a0", text="Hello", bbox=[12, 11, 48, 28], source="vlm")],
        text_source="vlm_spatial",
    )
    result = reconcile_with_alternatives(
        base,
        [AlternativeSourceDoc(document_ir=alt, provider_name="vlm")],
    )
    base_word = result.document_ir.pages[0].words[0]
    assert len(base_word.alternative_sources) == 1
    assert base_word.alternative_sources[0].provider == "vlm"
    assert base_word.alternative_sources[0].text == "Hello"
    # VLM_USED_FOR_EXTRACTION recorded since a VLM source contributed.
    codes = {w.code for w in result.warnings}
    assert "VLM_USED_FOR_EXTRACTION" in codes


def test_reconcile_emits_no_bbox_warning_and_does_not_pollute_base() -> None:
    base = _doc([_word(id="b0", text="Hello", bbox=[10, 10, 50, 30])])
    alt = _doc(
        [_word(id="a0", text="Hello", bbox=None, source="vlm")],
        text_source="vlm_markdown",
    )
    result = reconcile_with_alternatives(
        base,
        [AlternativeSourceDoc(document_ir=alt, provider_name="kosmos25")],
    )
    base_word = result.document_ir.pages[0].words[0]
    assert base_word.alternative_sources == []
    codes = {w.code for w in result.warnings}
    assert "VLM_OUTPUT_HAS_NO_BBOXES" in codes


def test_reconcile_emits_conflict_when_alt_text_differs() -> None:
    base = _doc([_word(id="b0", text="Hello", bbox=[10, 10, 50, 30])])
    alt = _doc(
        [_word(id="a0", text="World", bbox=[12, 11, 48, 28], source="vlm")],
        text_source="vlm_spatial",
    )
    result = reconcile_with_alternatives(
        base,
        [AlternativeSourceDoc(document_ir=alt, provider_name="kosmos25")],
    )
    codes = {w.code for w in result.warnings}
    assert "VLM_OUTPUT_CONFLICTS_WITH_OCR" in codes


def test_reconcile_text_disagree_ignores_punctuation_and_case() -> None:
    base = _doc([_word(id="b0", text="Hello,", bbox=[10, 10, 50, 30])])
    alt = _doc(
        [_word(id="a0", text="hello", bbox=[12, 11, 48, 28], source="vlm")],
        text_source="vlm_spatial",
    )
    result = reconcile_with_alternatives(
        base,
        [AlternativeSourceDoc(document_ir=alt, provider_name="kosmos25")],
    )
    codes = {w.code for w in result.warnings}
    assert "VLM_OUTPUT_CONFLICTS_WITH_OCR" not in codes


def test_reconcile_emits_review_warning_for_generative_alt() -> None:
    base = _doc([_word(id="b0", text="Hello", bbox=[10, 10, 50, 30])])
    alt = _doc(
        [_word(id="a0", text="Hello", bbox=[200, 200, 250, 220], source="vlm")],
        text_source="vlm_spatial",
    )
    result = reconcile_with_alternatives(
        base,
        [AlternativeSourceDoc(
            document_ir=alt,
            provider_name="kosmos25",
            generative=True,
            hallucination_risk=True,
        )],
    )
    codes = {w.code for w in result.warnings}
    assert "VLM_GENERATIVE_OUTPUT_REQUIRES_REVIEW" in codes
    assert "VLM_USED_FOR_EXTRACTION" in codes


def test_reconcile_with_no_alternatives_is_a_noop() -> None:
    base = _doc([_word(id="b0", text="Hello", bbox=[10, 10, 50, 30])])
    result = reconcile_with_alternatives(base, [])
    assert result.warnings == []
    assert result.document_ir.pages[0].words[0].alternative_sources == []


def test_reconcile_skips_pages_missing_in_base() -> None:
    base = _doc([_word(id="b0", text="Hi", bbox=[0, 0, 5, 5])], page_index=0)
    alt = _doc(
        [_word(id="a0", text="Hi", bbox=[0, 0, 5, 5], source="vlm")],
        page_index=99,
        text_source="vlm_spatial",
    )
    result = reconcile_with_alternatives(
        base,
        [AlternativeSourceDoc(document_ir=alt, provider_name="vlm")],
    )
    # Alt page 99 has no matching base page → silently skipped, no warnings.
    assert result.warnings == []
    assert result.document_ir.pages[0].words[0].alternative_sources == []


def test_reconcile_vlm_only_text_with_no_overlap_does_not_drive_redaction() -> None:
    """VLM word that has a bbox but doesn't overlap any base word must NOT be
    appended to base.alternative_sources — image redaction must only consume
    bboxes from base (non-generative) sources."""
    base = _doc([_word(id="b0", text="Hello", bbox=[10, 10, 50, 30])])
    alt = _doc(
        [_word(id="a0", text="Extra", bbox=[500, 500, 600, 520], source="vlm")],
        text_source="vlm_spatial",
    )
    result = reconcile_with_alternatives(
        base,
        [AlternativeSourceDoc(document_ir=alt, provider_name="kosmos25")],
    )
    base_word = result.document_ir.pages[0].words[0]
    # Base word has zero alternative_sources because alt didn't overlap any base word.
    assert base_word.alternative_sources == []
    codes = {w.code for w in result.warnings}
    assert "VLM_USED_FOR_EXTRACTION" in codes


def test_reconcile_warnings_are_deduplicated() -> None:
    base = _doc([_word(id="b0", text="Hello", bbox=[10, 10, 50, 30])])
    # Two alt words on same page, both without bboxes — the warning content
    # differs by message text, so dedup is per (code, page_index, message).
    alt = _doc(
        [
            _word(id="a0", text="X", bbox=None, source="vlm"),
            _word(id="a1", text="Y", bbox=None, source="vlm"),
        ],
        text_source="vlm_markdown",
    )
    result = reconcile_with_alternatives(
        base,
        [AlternativeSourceDoc(
            document_ir=alt,
            provider_name="kosmos25",
            generative=True,
        )],
    )
    # No raw exact duplicates (warnings carry distinct provider/text wording);
    # ensure we still see the "VLM_GENERATIVE_OUTPUT_REQUIRES_REVIEW" summary
    # warning emitted exactly once at end.
    summary_count = sum(
        1
        for w in result.warnings
        if w.code == "VLM_GENERATIVE_OUTPUT_REQUIRES_REVIEW"
        and w.page_index is None
    )
    assert summary_count == 1
