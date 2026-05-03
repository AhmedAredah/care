"""QA gate / fail-closed logic tests."""
from __future__ import annotations

from care.extraction.diagram_extractor import DiagramExtraction
from care.extraction.narrative_extractor import NarrativeExtraction
from care.review import build_qa_report
from care.templates.detector import TemplateMatch, TemplateMatchEvidence


def _evidence(**overrides) -> TemplateMatchEvidence:
    base = dict(
        anchor_text_found=["Crash"],
        anchor_text_missing=[],
        form_number_match="EX-CR-1",
        page_count=1,
        page_count_in_range=True,
        region_bboxes_plausible=True,
        candidate_scores={"t": 0.95},
    )
    base.update(overrides)
    return TemplateMatchEvidence(**base)


def _good_diagram() -> DiagramExtraction:
    return DiagramExtraction(
        page_index=0,
        bbox_norm=(0.1, 0.1, 0.9, 0.5),
        bbox_pixels=(80, 100, 720, 500),
        image_path="/tmp/diagram.png",
        confidence=0.9,
        requires_review=False,
        warnings=[],
    )


def _good_narrative() -> NarrativeExtraction:
    return NarrativeExtraction(
        page_index=0,
        text="Driver A traveling north",
        anchor_start="Narrative",
        anchor_end="Officer",
        anchor_start_found=True,
        anchor_end_found=True,
        bbox_norm=(0.05, 0.55, 0.95, 0.85),
        bbox_pixels=(30, 463, 565, 715),
        confidence=0.9,
        requires_review=False,
        warnings=[],
        text_source="native",
    )


def test_qa_allows_fully_known_extraction() -> None:
    match = TemplateMatch(
        template_id="example_state_crash_v1",
        version="1.0",
        confidence=0.95,
        evidence=_evidence(),
        warnings=[],
        requires_review=False,
    )
    qa = build_qa_report(match, _good_diagram(), _good_narrative())
    assert qa.export_decision == "ALLOW"
    assert qa.export_blocked is False
    assert qa.blocking_reasons == []
    assert qa.requires_human_review is False
    assert qa.template_confidence == 0.95
    assert qa.diagram_confidence == 0.9
    assert qa.narrative_confidence == 0.9


def test_qa_blocks_unknown_template() -> None:
    match = TemplateMatch(
        template_id="UNKNOWN",
        version=None,
        confidence=0.4,
        evidence=_evidence(),
        warnings=["TEMPLATE_UNKNOWN", "TEMPLATE_LOW_CONFIDENCE"],
        requires_review=True,
    )
    qa = build_qa_report(match, None, None)
    assert qa.export_blocked is True
    assert qa.export_decision == "BLOCK"
    assert qa.requires_human_review is True
    assert "TEMPLATE_UNKNOWN" in qa.qa_flags
    assert "TEMPLATE_LOW_CONFIDENCE" in qa.qa_flags
    assert any("UNKNOWN" in r for r in qa.blocking_reasons)


def test_qa_blocks_low_template_confidence_even_when_id_known() -> None:
    match = TemplateMatch(
        template_id="example_state_crash_v1",
        version="1.0",
        confidence=0.6,
        evidence=_evidence(),
        warnings=[],
        requires_review=False,
    )
    qa = build_qa_report(match, _good_diagram(), _good_narrative(),
                          template_confidence_threshold=0.85)
    assert qa.export_blocked is True
    assert "TEMPLATE_LOW_CONFIDENCE" in qa.qa_flags
    assert qa.requires_human_review is True


def test_qa_blocks_when_diagram_uncertain() -> None:
    match = TemplateMatch(
        template_id="example_state_crash_v1",
        version="1.0",
        confidence=0.95,
        evidence=_evidence(),
        warnings=[],
        requires_review=False,
    )
    diagram = DiagramExtraction(
        page_index=0,
        bbox_norm=(0.1, 0.1, 0.9, 0.5),
        confidence=0.4,
        requires_review=True,
        warnings=["DIAGRAM_REGION_UNCERTAIN"],
    )
    qa = build_qa_report(match, diagram, _good_narrative())
    assert qa.export_blocked is True
    assert "DIAGRAM_REGION_UNCERTAIN" in qa.qa_flags
    assert qa.requires_human_review is True


def test_qa_blocks_when_narrative_anchors_missing() -> None:
    match = TemplateMatch(
        template_id="example_state_crash_v1",
        version="1.0",
        confidence=0.95,
        evidence=_evidence(),
        warnings=[],
        requires_review=False,
    )
    narrative = NarrativeExtraction(
        page_index=0,
        text="some content",
        anchor_start="Narrative",
        anchor_end="Officer",
        anchor_start_found=False,
        anchor_end_found=True,
        confidence=0.4,
        requires_review=True,
        warnings=["NARRATIVE_ANCHORS_NOT_FOUND"],
    )
    qa = build_qa_report(match, _good_diagram(), narrative)
    assert qa.export_blocked is True
    assert "NARRATIVE_ANCHORS_NOT_FOUND" in qa.qa_flags


def test_qa_blocks_when_pii_cannot_be_mapped_to_image_coords() -> None:
    from care.pii.entities import PIIEntity

    match = TemplateMatch(
        template_id="example_state_crash_v1",
        version="1.0",
        confidence=0.95,
        evidence=_evidence(),
        warnings=[],
        requires_review=False,
    )
    unmapped = PIIEntity(
        entity_type="PHONE_NUMBER",
        text="555-1234",
        provider="regex",
        start_offset=0,
        end_offset=8,
        confidence=0.9,
        bbox=None,
        can_map_to_image_coordinates=False,
        page_index=0,
    )
    qa = build_qa_report(
        match,
        _good_diagram(),
        _good_narrative(),
        pii_entities_pages=[unmapped],
    )
    assert qa.export_blocked is True
    assert "PII_UNMAPPED" in qa.qa_flags
    assert qa.pii_unmapped_count == 1
    assert qa.requires_human_review is True


def test_qa_allows_when_every_pii_entity_has_bbox() -> None:
    from care.pii.entities import PIIEntity

    match = TemplateMatch(
        template_id="example_state_crash_v1",
        version="1.0",
        confidence=0.95,
        evidence=_evidence(),
        warnings=[],
        requires_review=False,
    )
    mapped = PIIEntity(
        entity_type="PHONE_NUMBER",
        text="555-1234",
        provider="regex",
        start_offset=0,
        end_offset=8,
        confidence=0.9,
        bbox=[10, 20, 100, 40],
        can_map_to_image_coordinates=True,
        page_index=0,
    )
    qa = build_qa_report(
        match,
        _good_diagram(),
        _good_narrative(),
        pii_entities_pages=[mapped],
    )
    assert qa.export_decision == "ALLOW"
    assert "PII_UNMAPPED" not in qa.qa_flags
    assert qa.pii_unmapped_count == 0


def test_qa_qa_flags_dedup_and_sorted() -> None:
    match = TemplateMatch(
        template_id="UNKNOWN",
        version=None,
        confidence=0.0,
        evidence=_evidence(page_count_in_range=False),
        warnings=["TEMPLATE_UNKNOWN", "TEMPLATE_LOW_CONFIDENCE"],
        requires_review=True,
    )
    qa = build_qa_report(match, None, None)
    assert qa.qa_flags == sorted(set(qa.qa_flags))
