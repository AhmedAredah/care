"""Narrative extractor + anchor helper tests."""
from __future__ import annotations

from care.document_ir import DocumentIR, Page, Provenance, Word
from care.extraction import extract_narrative, find_anchor_span
from care.templates import TemplateSchema


def _doc(tokens: list[str], text_source: str = "native") -> DocumentIR:
    prov = Provenance(provider="t", provider_type=text_source)
    words = [
        Word(
            id=f"p0_w{i:05d}",
            text=t,
            source=text_source,
            source_provider_type=text_source,
            provenance=prov,
        )
        for i, t in enumerate(tokens)
    ]
    return DocumentIR(
        document_id="d",
        source_file_name="x.pdf",
        source_sha256="0" * 64,
        file_type="pdf",
        created_at="2026-05-01T00:00:00Z",
        pages=[Page(page_index=0, width=595, height=842, text_source=text_source, words=words)],
    )


def _template(anchor_start="Narrative", anchor_end="Officer") -> TemplateSchema:
    return TemplateSchema.model_validate(
        {
            "template_id": "t",
            "regions": {
                "narrative": {
                    "page": 0,
                    "anchor_start": anchor_start,
                    "anchor_end": anchor_end,
                    "bbox_norm": [0.05, 0.55, 0.95, 0.85],
                }
            },
        }
    )


# ---------- find_anchor_span ----------


def test_find_anchor_span_extracts_between_anchors() -> None:
    text = "Header Narrative the body of the narrative Officer Smith"
    span = find_anchor_span(text, anchor_start="Narrative", anchor_end="Officer")
    assert span.text == "the body of the narrative"
    assert span.anchor_start_found and span.anchor_end_found


def test_find_anchor_span_case_insensitive_anchors() -> None:
    text = "MOCK CRASH REPORT Form: EX-CR-1 Diagram NARRATIVE Driver A. OFFICER X"
    span = find_anchor_span(text, anchor_start="Narrative", anchor_end="Officer")
    assert span.anchor_start_found
    assert span.anchor_end_found
    assert "Driver A" in span.text


def test_find_anchor_span_marks_missing_anchor() -> None:
    span = find_anchor_span("nothing here", anchor_start="Narrative", anchor_end="Officer")
    assert span.anchor_start_found is False
    assert span.anchor_end_found is False


# ---------- extract_narrative ----------


def test_extract_narrative_returns_none_when_no_region() -> None:
    template = TemplateSchema.model_validate({"template_id": "t"})
    assert extract_narrative(template, _doc(["a"])) is None


def test_extract_narrative_high_confidence_when_both_anchors_found() -> None:
    doc = _doc("Header Narrative Driver A traveling north Officer Smith".split())
    result = extract_narrative(_template(), doc)
    assert result is not None
    assert result.confidence >= 0.85
    assert "Driver A traveling north" in result.text
    assert result.requires_review is False
    assert result.bbox_norm == (0.05, 0.55, 0.95, 0.85)
    assert result.bbox_pixels is not None


def test_extract_narrative_missing_anchor_requires_review() -> None:
    doc = _doc("Header Driver A traveling north Officer Smith".split())  # no "Narrative"
    result = extract_narrative(_template(), doc)
    assert result is not None
    assert "NARRATIVE_ANCHORS_NOT_FOUND" in result.warnings
    assert result.requires_review is True
    assert result.confidence < 0.7


def test_extract_narrative_empty_span_marks_review() -> None:
    doc = _doc("Header NarrativeOfficer Smith".split())
    # The two anchors are adjacent; the span between them is empty.
    result = extract_narrative(_template(), doc)
    assert result is not None
    assert result.text == ""
    assert "NARRATIVE_EMPTY" in result.warnings
    assert result.requires_review is True
    assert result.confidence == 0.0


def test_extract_narrative_records_text_source() -> None:
    doc = _doc(
        "Narrative body content Officer".split(),
        text_source="ocr",
    )
    result = extract_narrative(_template(), doc)
    assert result is not None
    assert result.text_source == "ocr"
