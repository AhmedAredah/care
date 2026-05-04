"""Multi-page region + continuation tests (post-Phase-7).

Covers:
- TemplateRegion.page accepts int OR list[int]
- candidate_pages() normalizes to a list
- ContinuationSpec validates pages and bbox shape
- diagram extractor falls back across candidate pages
- narrative extractor finds the right primary page when text shifts
- narrative continuation concatenates text until anchor_end
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from pydantic import ValidationError

from care.document_ir.models import (
    DocumentIR,
    Page,
    Provenance,
    Word,
)
from care.extraction.diagram_extractor import extract_diagram
from care.extraction.narrative_extractor import extract_narrative
from care.templates.schemas import (
    ContinuationSpec,
    TemplateRegion,
    TemplateSchema,
)

# ----- schema tests --------------------------------------------------------


def test_region_page_accepts_single_int_default() -> None:
    r = TemplateRegion(bbox_norm=[0.1, 0.1, 0.9, 0.9])
    assert r.page == 0
    assert r.candidate_pages() == [0]


def test_region_page_accepts_explicit_int() -> None:
    r = TemplateRegion(page=2, bbox_norm=[0.1, 0.1, 0.9, 0.9])
    assert r.page == 2
    assert r.candidate_pages() == [2]


def test_region_page_accepts_list() -> None:
    r = TemplateRegion(page=[0, 1, 2], bbox_norm=[0.1, 0.1, 0.9, 0.9])
    assert r.candidate_pages() == [0, 1, 2]


def test_region_page_list_dedup_preserves_order() -> None:
    r = TemplateRegion(page=[1, 0, 1, 2, 0], bbox_norm=[0.1, 0.1, 0.9, 0.9])
    assert r.candidate_pages() == [1, 0, 2]


def test_region_page_rejects_negative_int() -> None:
    with pytest.raises(ValidationError):
        TemplateRegion(page=-1, bbox_norm=[0.1, 0.1, 0.9, 0.9])


def test_region_page_rejects_empty_list() -> None:
    with pytest.raises(ValidationError):
        TemplateRegion(page=[], bbox_norm=[0.1, 0.1, 0.9, 0.9])


def test_region_page_rejects_non_int_list_entries() -> None:
    with pytest.raises(ValidationError):
        TemplateRegion(page=[0, "x"], bbox_norm=[0.1, 0.1, 0.9, 0.9])  # type: ignore[list-item]


def test_region_page_rejects_negative_in_list() -> None:
    with pytest.raises(ValidationError):
        TemplateRegion(page=[0, -1], bbox_norm=[0.1, 0.1, 0.9, 0.9])


def test_continuation_spec_dedups_pages_and_validates_bbox() -> None:
    cont = ContinuationSpec(
        pages=[1, 2, 1, 3],
        anchor_end="Officer",
        bbox_norm=[0.0, 0.0, 1.0, 1.0],
    )
    assert cont.pages == [1, 2, 3]
    assert cont.bbox_norm == [0.0, 0.0, 1.0, 1.0]


def test_continuation_spec_rejects_bad_bbox() -> None:
    with pytest.raises(ValidationError):
        ContinuationSpec(pages=[1], bbox_norm=[1.5, 0.0, 2.0, 0.5])


def test_continuation_spec_rejects_negative_pages() -> None:
    with pytest.raises(ValidationError):
        ContinuationSpec(pages=[-1])


# ----- extractor helpers ---------------------------------------------------


def _word(id_: str, text: str) -> Word:
    return Word(
        id=id_,
        text=text,
        bbox=[0.0, 0.0, 1.0, 1.0],
        source="native_pdf",
        source_provider_type="native_pdf",
        provenance=Provenance(
            provider="native_pdf",
            provider_version="0",
            provider_type="native_pdf",
        ),
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


# ----- narrative: candidate pages -----------------------------------------


def test_narrative_picks_page_containing_anchor_start() -> None:
    """Page 0 has only header text; narrative actually appears on page 1."""
    doc = _doc(
        [
            "Example Crash Report Form: EX-CR-99 boilerplate page header",
            "Narrative The vehicle traveled north Officer Smith signed",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page=[0, 1],
                bbox_norm=[0.0, 0.0, 1.0, 1.0],
                anchor_start="Narrative",
                anchor_end="Officer",
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    assert result.page_index == 1
    assert "vehicle traveled north" in result.text
    assert result.anchor_start_found is True
    assert result.anchor_end_found is True
    assert result.spans_pages == [1]


def test_narrative_falls_back_to_first_candidate_when_no_anchor_match() -> None:
    """No page contains the anchor → empty extraction, flag uncertain boundaries."""
    doc = _doc(["page0 boilerplate", "page1 unrelated text"])
    template = _template(
        {
            "narrative": TemplateRegion(
                page=[0, 1],
                bbox_norm=[0.0, 0.0, 1.0, 1.0],
                anchor_start="Narrative",
                anchor_end="Officer",
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    assert result.requires_review is True
    # When no candidate page scores > 0, the extractor returns an empty
    # extraction tagged with NARRATIVE_BOUNDARIES_UNCERTAIN (more
    # accurate than NARRATIVE_ANCHORS_NOT_FOUND, which now only fires
    # when SOME anchor was found).
    assert "NARRATIVE_BOUNDARIES_UNCERTAIN" in result.warnings


# ----- narrative: continuation --------------------------------------------


def test_narrative_continuation_concatenates_until_anchor_end() -> None:
    """Long narrative spans page 0 -> page 1; anchor_end finally appears
    on page 1."""
    doc = _doc(
        [
            "Header Narrative The vehicle began traveling north on Main "
            "and continued for several blocks after the intersection",
            "the second vehicle approached from the east and the impact "
            "occurred at 14:32 Officer Smith arrived shortly afterward",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page=0,
                bbox_norm=[0.0, 0.0, 1.0, 1.0],
                anchor_start="Narrative",
                anchor_end="Officer",
                continuation=ContinuationSpec(pages=[1], anchor_end="Officer"),
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    assert result.page_index == 0
    assert "vehicle began traveling north" in result.text
    assert "impact occurred at 14:32" in result.text
    assert "Officer" not in result.text  # cut off at anchor_end
    assert result.anchor_end_found is True
    assert result.spans_pages == [0, 1]
    assert "NARRATIVE_SPANS_PAGES" in result.warnings


def test_narrative_continuation_runs_out_without_anchor_end() -> None:
    """Continuation pages exhausted without finding anchor_end → review."""
    doc = _doc(
        [
            "Header Narrative The vehicle began traveling north",
            "the second vehicle approached from the east",
        ]
    )
    template = _template(
        {
            "narrative": TemplateRegion(
                page=0,
                bbox_norm=[0.0, 0.0, 1.0, 1.0],
                anchor_start="Narrative",
                anchor_end="Officer",
                continuation=ContinuationSpec(pages=[1], anchor_end="Officer"),
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    assert result.anchor_end_found is False
    assert result.requires_review is True
    assert "NARRATIVE_ANCHORS_NOT_FOUND" in result.warnings
    assert result.spans_pages == [0, 1]


def test_narrative_continuation_skips_invalid_pages() -> None:
    """Continuation pages that don't exist in the doc are silently skipped."""
    doc = _doc(["Header Narrative body Officer Smith"])
    template = _template(
        {
            "narrative": TemplateRegion(
                page=0,
                anchor_start="Narrative",
                anchor_end="Officer",
                continuation=ContinuationSpec(pages=[5, 6], anchor_end="Officer"),
            )
        }
    )
    result = extract_narrative(template, doc)
    assert result is not None
    # Anchor_end already found on primary; continuation is irrelevant.
    assert result.anchor_end_found is True
    assert result.spans_pages == [0]


# ----- diagram: candidate pages -------------------------------------------


def _make_blank_image(path: Path, *, width: int = 100, height: int = 100) -> Path:
    Image.new("RGB", (width, height), color="white").save(path, format="PNG")
    return path


def test_diagram_uses_first_available_candidate_page(tmp_path: Path) -> None:
    """page=[0, 1] but only page 1's source image is on disk → use page 1."""
    doc = _doc(["page0 placeholder", "page1 placeholder"], width=100, height=100)
    template = _template(
        {
            "diagram": TemplateRegion(
                page=[0, 1],
                bbox_norm=[0.0, 0.0, 1.0, 1.0],
            )
        }
    )
    page1_image = _make_blank_image(tmp_path / "p1.png")
    result = extract_diagram(
        template,
        doc,
        work_dir=tmp_path / "work",
        source_image_paths={1: page1_image},  # page 0 deliberately missing
    )
    assert result is not None
    assert result.page_index == 1
    assert result.image_path is not None
    # Phase 7+: DIAGRAM_CANDIDATE_PAGE_USED replaces the earlier
    # DIAGRAM_PAGE_FALLBACK flag and is the canonical signal that a
    # non-primary candidate was selected.
    assert "DIAGRAM_CANDIDATE_PAGE_USED" in result.warnings


def test_diagram_prefers_first_candidate_when_both_available(tmp_path: Path) -> None:
    doc = _doc(["page0 placeholder", "page1 placeholder"], width=100, height=100)
    template = _template(
        {
            "diagram": TemplateRegion(
                page=[0, 1],
                bbox_norm=[0.0, 0.0, 1.0, 1.0],
            )
        }
    )
    p0 = _make_blank_image(tmp_path / "p0.png")
    p1 = _make_blank_image(tmp_path / "p1.png")
    result = extract_diagram(
        template,
        doc,
        work_dir=tmp_path / "work",
        source_image_paths={0: p0, 1: p1},
    )
    assert result is not None
    assert result.page_index == 0
    assert "DIAGRAM_CANDIDATE_PAGE_USED" not in result.warnings


def test_diagram_returns_uncertain_when_no_candidate_renders(tmp_path: Path) -> None:
    doc = _doc(["page0", "page1"], width=100, height=100)
    template = _template(
        {
            "diagram": TemplateRegion(
                page=[0, 1],
                bbox_norm=[0.0, 0.0, 1.0, 1.0],
            )
        }
    )
    result = extract_diagram(
        template,
        doc,
        work_dir=tmp_path / "work",
        source_image_paths={},  # no rendered images at all
    )
    assert result is not None
    assert result.image_path is None
    assert result.requires_review is True
    assert "DIAGRAM_REGION_UNCERTAIN" in result.warnings
