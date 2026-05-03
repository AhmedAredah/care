"""manifest.json contents."""
from __future__ import annotations

from care.core.config import AppConfig
from care.export import build_manifest
from care.extraction.diagram_extractor import DiagramExtraction
from care.extraction.narrative_extractor import NarrativeExtraction
from care.ingestion.file_manifest import FileEntry
from care.pdf.base import FileInspection
from care.review import build_qa_report
from care.templates.detector import TemplateMatch, TemplateMatchEvidence
from care.workers.pipeline import ReportArtifact


def _build_artifact() -> ReportArtifact:
    template_match = TemplateMatch(
        template_id="example_state_crash_v1",
        version="1.0",
        confidence=0.95,
        evidence=TemplateMatchEvidence(
            anchor_text_found=["Crash"],
            anchor_text_missing=[],
            form_number_match="EX-CR-1",
            page_count=1,
            page_count_in_range=True,
            region_bboxes_plausible=True,
            candidate_scores={"example_state_crash_v1": 0.95},
        ),
        warnings=[],
        requires_review=False,
    )
    diagram = DiagramExtraction(
        page_index=0, bbox_norm=(0.05, 0.15, 0.95, 0.55), confidence=0.9
    )
    narrative = NarrativeExtraction(
        page_index=0, text="something", confidence=0.9, text_source="native"
    )
    qa = build_qa_report(template_match, diagram, narrative, pii_entities_pages=[])
    file_entry = FileEntry(
        path="/x/example.pdf",
        name="example.pdf",
        size_bytes=100,
        sha256="a" * 64,
        file_type="pdf",
        extension=".pdf",
        discovered_at="2026-05-01T00:00:00Z",
    )
    inspection = FileInspection(
        file_type="pdf",
        page_count=1,
        page_dimensions=[(595, 842)],
        has_text_layer=True,
        appears_image_only=False,
        requires_ocr=False,
    )
    return ReportArtifact(
        file_entry=file_entry,
        inspection=inspection,
        document_ir=None,  # not used by manifest builder
        text_source="native",
        template_match=template_match,
        diagram=diagram,
        narrative=narrative,
        qa=qa,
    )


def test_manifest_records_required_keys() -> None:
    cfg = AppConfig()
    manifest = build_manifest(_build_artifact(), cfg)
    for key in (
        "source_sha256", "source_file_name",
        "template_id", "template_version", "template_confidence",
        "ocr_provider", "pii_provider_chain", "redaction_policy",
        "export_contains_original_pdf", "export_contains_unredacted_text",
        "requires_human_review", "created_at",
    ):
        assert key in manifest


def test_manifest_marks_no_original_no_unredacted_no_raw() -> None:
    manifest = build_manifest(_build_artifact(), AppConfig())
    assert manifest["export_contains_original_pdf"] is False
    assert manifest["export_contains_unredacted_text"] is False
    assert manifest["export_contains_raw_ocr_or_vlm_output"] is False


def test_manifest_records_pii_provider_chain_from_config() -> None:
    cfg = AppConfig()
    cfg.pii.provider_chain = ["regex", "presidio"]
    manifest = build_manifest(_build_artifact(), cfg)
    assert manifest["pii_provider_chain"] == ["regex", "presidio"]
