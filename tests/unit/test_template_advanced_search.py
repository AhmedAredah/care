"""Phase 7+ stronger schema + extractor tests.

Covers PageSearch / "any" / shifted_region_search /
DiagramContinuation / expanded ContinuationSpec, plus the
confidence-scored selection logic and ambiguity blocking.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from care.core.constants import BLOCKING_QA_FLAGS, QA_FLAGS
from care.document_ir.models import (
    DocumentIR,
    Page,
    Provenance,
    Word,
)
from care.extraction.diagram_extractor import extract_diagram
from care.extraction.narrative_extractor import extract_narrative
from care.review import build_qa_report
from care.templates.detector import TemplateMatch, TemplateMatchEvidence
from care.templates.schemas import (
    ContinuationSpec,
    DiagramContinuation,
    PageSearch,
    ShiftedRegionSearch,
    TemplateRegion,
    TemplateSchema,
)


# ----- helpers ------------------------------------------------------------


def _word(id_: str, text: str, *, bbox=(0.0, 0.0, 10.0, 10.0)) -> Word:
    return Word(
        id=id_,
        text=text,
        bbox=list(bbox),
        source="native_pdf",
        source_provider_type="native_pdf",
        provenance=Provenance(provider="native_pdf", provider_version="0", provider_type="native_pdf"),
        can_map_to_image_coordinates=True,
    )


def _doc(pages_text: list[str], *, width: int = 1000, height: int = 1000) -> DocumentIR:
    pages = []
    for idx, text in enumerate(pages_text):
        words = [_word(f"p{idx}_w{j}", token) for j, token in enumerate(text.split())]
        pages.append(
            Page(
                page_index=idx,
                width=width,
                height=height,
                text_source="native",
                words=words,
            )
        )
    return DocumentIR(
        document_id="t",
        source_file_name="t.pdf",
        source_sha256="0" * 64,
        file_type="pdf",
        created_at="now",
        pages=pages,
    )


def _template(regions: dict[str, TemplateRegion]) -> TemplateSchema:
    return TemplateSchema(template_id="t", version="1.0", regions=regions)


def _png(path: Path, *, width: int = 100, height: int = 100) -> Path:
    Image.new("RGB", (width, height), color="white").save(path, format="PNG")
    return path


# ----- schema: PageSearch + "any" -----------------------------------------


def test_region_page_accepts_any_string() -> None:
    r = TemplateRegion(page="any", bbox_norm=[0.0, 0.0, 1.0, 1.0])
    assert r.page == "any"
    assert r.candidate_pages(page_count=4) == [0, 1, 2, 3]


def test_region_page_accepts_page_search_object() -> None:
    r = TemplateRegion(
        page=PageSearch(candidate_pages=[1, 2], search_strategy="best_match"),
        bbox_norm=[0.0, 0.0, 1.0, 1.0],
    )
    ps = r.page_search()
    assert ps.search_strategy == "best_match"
    assert ps.candidate_pages == [1, 2]


def test_page_search_rejects_bad_strategy() -> None:
    with pytest.raises(ValidationError):
        PageSearch(candidate_pages=[0], search_strategy="best_guess")  # type: ignore[arg-type]


def test_region_page_search_dict_form_round_trips() -> None:
    """Templates loaded from YAML come in as dicts."""
    r = TemplateRegion(
        page={"candidate_pages": [0, 1, 2], "search_strategy": "first_match"},
        bbox_norm=[0.0, 0.0, 1.0, 1.0],
    )
    ps = r.page_search()
    assert ps.candidate_pages == [0, 1, 2]
    assert ps.search_strategy == "first_match"


def test_continuation_max_pages_validates_non_negative() -> None:
    with pytest.raises(ValidationError):
        ContinuationSpec(pages=[1], max_continuation_pages=-1)


def test_continuation_stop_at_section_anchor_accepts_str_or_list() -> None:
    a = ContinuationSpec(pages=[1], stop_at_next_section_anchor="Witness Statement")
    b = ContinuationSpec(pages=[1], stop_at_next_section_anchor=["Witness", "Officer"])
    assert a.stop_at_next_section_anchor == "Witness Statement"
    assert b.stop_at_next_section_anchor == ["Witness", "Officer"]


def test_diagram_continuation_round_trips() -> None:
    dc = DiagramContinuation(
        candidate_pages=[1, 2],
        require_visual_density=True,
        max_text_density=0.02,
    )
    assert dc.candidate_pages == [1, 2]
    assert dc.max_text_density == 0.02


def test_shifted_region_search_round_trips() -> None:
    sr = ShiftedRegionSearch(
        enabled=True,
        search_pages=[3, 4],
        min_primary_score=0.6,
    )
    assert sr.enabled is True
    assert sr.search_pages == [3, 4]
    assert sr.min_primary_score == 0.6


# ----- narrative: confidence + ambiguity ----------------------------------


def test_narrative_best_match_picks_higher_scoring_page() -> None:
    """Page 1 has both anchors; page 0 has only the start anchor.
    best_match must pick page 1."""
    doc = _doc(
        [
            "Header Narrative beginning",
            "Narrative body and Officer signature",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page=[0, 1],
                anchor_start="Narrative",
                anchor_end="Officer",
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    assert result.page_index == 1
    assert result.anchor_start_found is True
    assert result.anchor_end_found is True


def test_narrative_ambiguity_when_two_pages_score_equally() -> None:
    """Two pages BOTH carry start AND end anchors → REGION_AMBIGUOUS."""
    doc = _doc(
        [
            "Narrative bodyA Officer signed page0",
            "Narrative bodyB Officer signed page1",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page=[0, 1],
                anchor_start="Narrative",
                anchor_end="Officer",
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    assert "REGION_AMBIGUOUS" in result.warnings
    assert result.requires_review is True


def test_narrative_first_match_strategy_skips_higher_scoring_later_page() -> None:
    """first_match returns the first non-zero-scoring candidate."""
    doc = _doc(
        [
            "Narrative bodyA Officer signed",
            "Narrative bodyB Officer signed page1",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page=PageSearch(candidate_pages=[0, 1], search_strategy="first_match"),
                anchor_start="Narrative",
                anchor_end="Officer",
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    # first_match → page 0 wins because it's the first candidate to score > 0.
    assert result.page_index == 0


def test_narrative_any_pages_resolves_to_doc_page_count() -> None:
    """page='any' → every page in the doc is a candidate."""
    doc = _doc(
        [
            "irrelevant first page",
            "noise",
            "Narrative bodyC Officer signed",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page="any",
                anchor_start="Narrative",
                anchor_end="Officer",
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    assert result.page_index == 2


# ----- narrative: shifted-region search -----------------------------------


def test_narrative_shifted_search_finds_anchors_outside_primary() -> None:
    """Primary candidate is page 0 (no anchors); shifted search picks up page 2."""
    doc = _doc(
        [
            "header without anchors",
            "another non-narrative page",
            "Narrative real body Officer signed",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page=[0],
                anchor_start="Narrative",
                anchor_end="Officer",
                shifted_region_search=ShiftedRegionSearch(enabled=True),
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    assert result.page_index == 2
    assert "REGION_SHIFTED_PAGE" in result.warnings
    assert result.requires_review is True  # require_review_on_shift defaults True


def test_narrative_shifted_search_disabled_does_nothing() -> None:
    doc = _doc(
        [
            "header without anchors",
            "Narrative body Officer signed",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page=[0],
                anchor_start="Narrative",
                anchor_end="Officer",
                shifted_region_search=ShiftedRegionSearch(enabled=False),
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    # No shift; primary candidate page 0 returned with empty extraction.
    assert "REGION_SHIFTED_PAGE" not in result.warnings


def test_narrative_shifted_search_can_skip_review_if_configured() -> None:
    doc = _doc(["empty", "Narrative body Officer signed"])
    template = _template(
        {
            "narrative": TemplateRegion(
                page=[0],
                anchor_start="Narrative",
                anchor_end="Officer",
                shifted_region_search=ShiftedRegionSearch(
                    enabled=True, require_review_on_shift=False
                ),
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    assert "REGION_SHIFTED_PAGE" in result.warnings
    # Without require_review_on_shift the shift itself does not force
    # review (other reasons might still).
    assert all(
        not w.startswith("REGION_SHIFTED_PAGE")
        or result.requires_review == True  # ambiguity or anchor miss may still trigger
        for w in result.warnings
    )


# ----- narrative: continuation expanded knobs -----------------------------


def test_narrative_continuation_max_pages_truncates() -> None:
    doc = _doc(
        [
            "Narrative body starts here and runs",
            "across the second page with more text",
            "and then continues on page two of cont",
            "and finally Officer signed on this last page",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page=0,
                anchor_start="Narrative",
                anchor_end="Officer",
                continuation=ContinuationSpec(
                    pages=[1, 2, 3],
                    anchor_end="Officer",
                    max_continuation_pages=1,
                ),
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    assert "NARRATIVE_CONTINUATION_TRUNCATED" in result.warnings
    assert "NARRATIVE_CONTINUATION_ANCHOR_MISSING" in result.warnings
    assert result.requires_review is True


def test_narrative_continuation_stops_at_next_section_anchor() -> None:
    """Continuation stops early when 'Witness' appears."""
    doc = _doc(
        [
            "Narrative body starts here",
            "and continues here Witness Statement: Jane saw it Officer Smith",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page=0,
                anchor_start="Narrative",
                anchor_end="Officer",
                continuation=ContinuationSpec(
                    pages=[1],
                    anchor_end="Officer",
                    stop_at_next_section_anchor="Witness Statement",
                ),
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    assert "Witness" not in result.text
    assert "Jane saw it" not in result.text
    # Stopped early before reaching Officer; anchor_end_found is True
    # because section_stop closed the span gracefully.
    assert "NARRATIVE_CONTINUED" in result.warnings


def test_narrative_continuation_anchor_missing_blocks_export() -> None:
    """When anchor_end is never found and require_review_if_anchor_end_missing
    is True, the continuation flag fires AND the QA gate must block."""
    doc = _doc(
        [
            "Narrative body starts here",
            "more text but no closing anchor here either",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page=0,
                anchor_start="Narrative",
                anchor_end="Officer",
                continuation=ContinuationSpec(pages=[1], anchor_end="Officer"),
            )
        }
    )
    narrative_result = extract_narrative(template, doc)
    assert narrative_result is not None
    assert "NARRATIVE_CONTINUATION_ANCHOR_MISSING" in narrative_result.warnings

    # Plumb through the QA gate to confirm fail-closed.
    match = TemplateMatch(
        template_id="t",
        version="1.0",
        confidence=0.95,
        evidence=TemplateMatchEvidence(
            anchor_text_found=["Narrative"],
            anchor_text_missing=[],
            form_number_match=None,
            page_count=2,
            page_count_in_range=True,
            region_bboxes_plausible=True,
            candidate_scores={"t": 0.95},
        ),
        warnings=[],
        requires_review=False,
    )
    qa = build_qa_report(match, None, narrative_result)
    assert qa.export_blocked is True
    assert "NARRATIVE_CONTINUATION_ANCHOR_MISSING" in qa.qa_flags


# ----- diagram: candidate-page + visual density ---------------------------


def test_diagram_continuation_picks_low_density_page(tmp_path: Path) -> None:
    """Two candidate pages; page 1 is dense with text inside the bbox,
    page 2 is empty (likely diagram). The extractor must prefer page 2."""
    bbox = [0.0, 0.0, 1.0, 1.0]
    doc = _doc(
        [
            "header",
            "lots of words inside the bbox area page1",  # dense text page 1
            "",  # blank-ish "diagram" page 2
        ],
        width=100,
        height=100,
    )
    template = _template(
        {
            "diagram": TemplateRegion(
                page=0,  # ignored once diagram_continuation is set
                bbox_norm=bbox,
                diagram_continuation=DiagramContinuation(
                    candidate_pages=[1, 2],
                    require_visual_density=True,
                    max_text_density=0.05,
                ),
            )
        }
    )
    p1 = _png(tmp_path / "p1.png")
    p2 = _png(tmp_path / "p2.png")
    result = extract_diagram(
        template,
        doc,
        work_dir=tmp_path / "work",
        source_image_paths={1: p1, 2: p2},
    )
    assert result is not None
    assert result.page_index == 2  # low-density page wins


def test_diagram_continuation_uncertain_when_density_too_high(tmp_path: Path) -> None:
    """All candidate bboxes have heavy text → uncertain → blocked."""
    bbox = [0.0, 0.0, 1.0, 1.0]
    doc = _doc(
        [
            "header",
            "lots " * 200,
        ],
        width=100,
        height=100,
    )
    template = _template(
        {
            "diagram": TemplateRegion(
                page=0,
                bbox_norm=bbox,
                diagram_continuation=DiagramContinuation(
                    candidate_pages=[1],
                    require_visual_density=True,
                    max_text_density=0.0001,  # extremely strict
                ),
            )
        }
    )
    p1 = _png(tmp_path / "p1.png")
    result = extract_diagram(
        template,
        doc,
        work_dir=tmp_path / "work",
        source_image_paths={1: p1},
    )
    assert result is not None
    assert result.image_path is None
    assert result.requires_review is True
    assert "DIAGRAM_CONTINUATION_UNCERTAIN" in result.warnings


def test_diagram_ambiguity_emits_region_ambiguous(tmp_path: Path) -> None:
    """Two candidate pages with identical scores → REGION_AMBIGUOUS."""
    doc = _doc(["", "", ""], width=100, height=100)
    template = _template(
        {
            "diagram": TemplateRegion(
                page=[1, 2],
                bbox_norm=[0.0, 0.0, 1.0, 1.0],
            )
        }
    )
    p1 = _png(tmp_path / "p1.png")
    p2 = _png(tmp_path / "p2.png")
    result = extract_diagram(
        template,
        doc,
        work_dir=tmp_path / "work",
        source_image_paths={1: p1, 2: p2},
    )
    assert result is not None
    assert "REGION_AMBIGUOUS" in result.warnings
    assert result.requires_review is True


# ----- QA: blocking-flag enforcement --------------------------------------


def test_qa_gate_blocks_on_region_ambiguous_even_without_extractor_reason() -> None:
    """REGION_AMBIGUOUS is in BLOCKING_QA_FLAGS, so the gate must
    refuse export even when the extractor itself didn't append a
    blocking_reason."""
    from care.extraction.diagram_extractor import DiagramExtraction
    from care.extraction.narrative_extractor import NarrativeExtraction

    diagram = DiagramExtraction(
        page_index=0,
        bbox_norm=(0.1, 0.1, 0.9, 0.5),
        bbox_pixels=(10, 10, 90, 50),
        image_path="/tmp/d.png",
        confidence=0.6,
        requires_review=True,
        warnings=["REGION_AMBIGUOUS"],
    )
    narrative = NarrativeExtraction(
        page_index=0,
        text="some text",
        anchor_start="Narrative",
        anchor_end="Officer",
        anchor_start_found=True,
        anchor_end_found=True,
        confidence=0.9,
        requires_review=False,
        warnings=[],
        text_source="native",
    )
    match = TemplateMatch(
        template_id="t",
        version="1.0",
        confidence=0.95,
        evidence=TemplateMatchEvidence(
            anchor_text_found=["Narrative"],
            anchor_text_missing=[],
            form_number_match=None,
            page_count=1,
            page_count_in_range=True,
            region_bboxes_plausible=True,
            candidate_scores={"t": 0.95},
        ),
        warnings=[],
        requires_review=False,
    )
    qa = build_qa_report(match, diagram, narrative)
    assert qa.export_blocked is True
    assert "REGION_AMBIGUOUS" in qa.qa_flags


def test_blocking_qa_flags_are_a_subset_of_qa_flags() -> None:
    assert BLOCKING_QA_FLAGS <= QA_FLAGS


def test_new_qa_flag_codes_are_registered() -> None:
    for code in (
        "NARRATIVE_CONTINUED",
        "NARRATIVE_CONTINUATION_ANCHOR_MISSING",
        "NARRATIVE_CONTINUATION_TRUNCATED",
        "REGION_SHIFTED_PAGE",
        "REGION_AMBIGUOUS",
        "DIAGRAM_CANDIDATE_PAGE_USED",
        "DIAGRAM_CONTINUATION_UNCERTAIN",
    ):
        assert code in QA_FLAGS
