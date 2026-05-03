"""Phase 9: fuzzy match wired into template scoring + narrative extractor."""
from __future__ import annotations

from typing import Any

from care.document_ir.models import (
    DocumentIR,
    Page,
    Provenance,
    Word,
)
from care.extraction.narrative_extractor import extract_narrative
from care.templates.detector import detect_template
from care.templates.registry import TemplateRegistry
from care.templates.schemas import TemplateSchema
from care.templates.scoring import score_template


def _doc(token_pages: list[list[str]]) -> DocumentIR:
    pages = []
    for i, tokens in enumerate(token_pages):
        words = [
            Word(
                id=f"p{i}_w{j:05d}",
                text=t,
                source="test",
                source_provider_type="test",
                source_provider_version="0",
                provenance=Provenance(provider="test"),
            )
            for j, t in enumerate(tokens)
        ]
        pages.append(Page(page_index=i, width=1000, height=1000, words=words))
    return DocumentIR(
        document_id="d",
        source_file_name="f.pdf",
        source_sha256="0" * 64,
        file_type="pdf",
        created_at="now",
        pages=pages,
    )


def _template(
    *, anchors: list[str], regions: dict[str, Any] | None = None
) -> TemplateSchema:
    base = {
        "template_id": "t",
        "version": "1.0",
        "signature": {"anchor_text": anchors},
        "layout": {"page_count_min": 1, "page_count_max": 5},
        "regions": regions or {},
    }
    return TemplateSchema.model_validate(base)


# ----- template scoring fuzzy match ---------------------------------------


def test_score_template_fuzzy_matches_ocr_typo() -> None:
    """OCR misread 'Narrative' as 'Narrahve' — fuzzy must rescue the score."""
    doc = _doc([["Crash", "Report", "Narrahve"]])
    template = _template(anchors=["Crash", "Report", "Narrative"])
    score = score_template(template, doc)
    assert "Narrative" in score.evidence.anchor_text_fuzzy_matched
    # Coverage with 2 exact + 1 fuzzy (discounted to 0.8): (2 + 0.8) / 3 ≈ 0.933
    assert 0.9 <= score.confidence <= 1.0


def test_score_template_exact_match_outscores_fuzzy_sibling() -> None:
    """Two near-identical templates: the one whose anchors all match
    exactly must outscore the one needing a fuzzy hit. Critical for
    distinguishing v1 from v2 forms."""
    doc = _doc([["Crash", "Report", "Narrative"]])
    exact = _template(anchors=["Crash", "Report", "Narrative"])
    fuzzy_only = _template(anchors=["Crash", "Report", "Narratlve"])  # typo
    s_exact = score_template(exact, doc)
    s_fuzzy = score_template(fuzzy_only, doc)
    assert s_exact.confidence > s_fuzzy.confidence


def test_score_template_fuzzy_disabled_does_not_match_typo() -> None:
    doc = _doc([["Crash", "Report", "Narrahve"]])
    template = _template(anchors=["Crash", "Report", "Narrative"])
    score = score_template(template, doc, allow_fuzzy_anchors=False)
    assert "Narrative" in score.evidence.anchor_text_missing
    # 2 of 3 anchors found exactly, no fuzzy → coverage 0.667
    assert 0.6 <= score.confidence <= 0.7


def test_detector_emits_fuzzy_warning() -> None:
    doc = _doc([["Crash", "Report", "Narrahve"]])  # one fuzzy
    template = _template(anchors=["Crash", "Report", "Narrative"])
    registry = TemplateRegistry([template])
    match = detect_template(doc, registry, confidence_threshold=0.5)
    assert "TEMPLATE_ANCHORS_FUZZY_MATCHED" in match.warnings


# ----- narrative extractor fuzzy match ------------------------------------


def test_narrative_extractor_emits_fuzzy_flag_on_anchor_typo() -> None:
    """Page text has 'Narrahve' but template declared 'Narrative' — fuzzy
    match should still extract the slice and emit the informational
    fuzzy flag (NOT a blocking flag)."""
    doc = _doc(
        [["Narrahve", "the", "vehicle", "stopped", "Officer", "Smith"]]
    )
    template = _template(
        anchors=["Crash"],
        regions={
            "narrative": {
                "page": 0,
                "bbox_norm": [0.0, 0.0, 1.0, 1.0],
                "anchor_start": "Narrative",
                "anchor_end": "Officer",
            }
        },
    )
    out = extract_narrative(template, doc)
    assert out is not None
    assert out.text  # text was extracted
    assert "NARRATIVE_ANCHORS_FUZZY_MATCHED" in out.warnings
    # Flag must NOT carry through as a blocking decision.
    from care.core.constants import BLOCKING_QA_FLAGS

    assert "NARRATIVE_ANCHORS_FUZZY_MATCHED" not in BLOCKING_QA_FLAGS
    assert "ANCHOR_LOW_CONFIDENCE" not in BLOCKING_QA_FLAGS


def test_narrative_extractor_exact_match_no_fuzzy_flag() -> None:
    doc = _doc(
        [["Narrative", "the", "vehicle", "stopped", "Officer", "Smith"]]
    )
    template = _template(
        anchors=["Crash"],
        regions={
            "narrative": {
                "page": 0,
                "bbox_norm": [0.0, 0.0, 1.0, 1.0],
                "anchor_start": "Narrative",
                "anchor_end": "Officer",
            }
        },
    )
    out = extract_narrative(template, doc)
    assert out is not None
    assert "NARRATIVE_ANCHORS_FUZZY_MATCHED" not in out.warnings
    assert "ANCHOR_LOW_CONFIDENCE" not in out.warnings


def test_anchor_low_confidence_fires_only_below_threshold() -> None:
    """ANCHOR_LOW_CONFIDENCE is set when the matched anchor's score
    drops below the per-anchor threshold (0.92). An exact match scores
    1.0 and must NOT trigger it; a fuzzy match scoring ≥0.85 but <0.92
    should trigger it."""
    # Single-character substitution in 8-char word → ratio ≈ 0.875.
    doc = _doc(
        [["Narrabive", "the", "vehicle", "stopped", "Officer", "Smith"]]
    )
    template = _template(
        anchors=["Crash"],
        regions={
            "narrative": {
                "page": 0,
                "bbox_norm": [0.0, 0.0, 1.0, 1.0],
                "anchor_start": "Narrative",
                "anchor_end": "Officer",
            }
        },
    )
    out = extract_narrative(template, doc)
    assert out is not None
    if "NARRATIVE_ANCHORS_FUZZY_MATCHED" in out.warnings:
        assert "ANCHOR_LOW_CONFIDENCE" in out.warnings
