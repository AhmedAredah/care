"""Template detector behavior."""
from __future__ import annotations

from care.document_ir import DocumentIR, Page, Provenance, Word
from care.templates import (
    TemplateRegistry,
    TemplateSchema,
    detect_template,
)


def _doc(tokens: list[str]) -> DocumentIR:
    prov = Provenance(provider="test", provider_type="test")
    words = [
        Word(
            id=f"p0_w{i:05d}",
            text=t,
            source="test",
            source_provider_type="test",
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
        pages=[Page(page_index=0, width=595, height=842, words=words)],
    )


def _crash_template() -> TemplateSchema:
    return TemplateSchema.model_validate(
        {
            "template_id": "example_state_crash_v1",
            "version": "1.0",
            "signature": {
                "anchor_text": ["Example Crash Report", "Narrative", "Diagram"],
                "form_number_regex": "EX-CR-[0-9]+",
            },
            "layout": {"page_count_min": 1, "page_count_max": 3},
            "regions": {
                "diagram": {"page": 0, "bbox_norm": [0.05, 0.15, 0.95, 0.55]},
                "narrative": {
                    "page": 0,
                    "anchor_start": "Narrative",
                    "anchor_end": "Officer",
                    "bbox_norm": [0.05, 0.55, 0.95, 0.85],
                },
            },
        }
    )


def test_empty_registry_returns_unknown() -> None:
    match = detect_template(_doc(["anything"]), TemplateRegistry())
    assert match.template_id == "UNKNOWN"
    assert match.confidence == 0.0
    assert "TEMPLATE_UNKNOWN" in match.warnings
    assert match.requires_review is True


def test_known_template_meets_threshold() -> None:
    doc = _doc(
        "Example Crash Report Form: EX-CR-12345 Diagram Narrative "
        "Driver A traveling north Officer Synthetic".split()
    )
    registry = TemplateRegistry([_crash_template()])
    match = detect_template(doc, registry, confidence_threshold=0.85)
    assert match.template_id == "example_state_crash_v1"
    assert match.confidence >= 0.85
    assert match.requires_review is False
    assert match.evidence.anchor_text_missing == []


def test_below_threshold_returns_unknown_with_review() -> None:
    doc = _doc(["Random", "document", "with", "no", "anchors"])
    registry = TemplateRegistry([_crash_template()])
    match = detect_template(doc, registry, confidence_threshold=0.85)
    assert match.template_id == "UNKNOWN"
    assert "TEMPLATE_UNKNOWN" in match.warnings
    assert "TEMPLATE_LOW_CONFIDENCE" in match.warnings
    assert match.requires_review is True


def test_page_count_out_of_range_marks_unknown() -> None:
    # Build a 5-page doc; template caps at 3 pages.
    pages = [Page(page_index=i, width=595, height=842, words=[]) for i in range(5)]
    doc = DocumentIR(
        document_id="d",
        source_file_name="x.pdf",
        source_sha256="0" * 64,
        file_type="pdf",
        created_at="2026-05-01T00:00:00Z",
        pages=pages,
    )
    match = detect_template(doc, TemplateRegistry([_crash_template()]))
    assert match.template_id == "UNKNOWN"
    assert match.evidence.page_count_in_range is False
    assert "TEMPLATE_PAGE_COUNT_OUT_OF_RANGE" in match.warnings
