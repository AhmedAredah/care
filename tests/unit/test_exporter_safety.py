"""Exporter safety: refuses to write when QA blocked."""
from __future__ import annotations

from pathlib import Path

from care.core.config import AppConfig
from care.export import export_artifact
from care.extraction.diagram_extractor import DiagramExtraction
from care.extraction.narrative_extractor import NarrativeExtraction
from care.ingestion.file_manifest import FileEntry
from care.pdf.base import FileInspection
from care.review.qa_flags import QAReport
from care.templates.detector import TemplateMatch, TemplateMatchEvidence
from care.workers.pipeline import ReportArtifact


def _artifact_with_qa(qa: QAReport) -> ReportArtifact:
    return ReportArtifact(
        file_entry=FileEntry(
            path="/x/example.pdf",
            name="example.pdf",
            size_bytes=10,
            sha256="b" * 64,
            file_type="pdf",
            extension=".pdf",
            discovered_at="2026-05-01T00:00:00Z",
        ),
        inspection=FileInspection(
            file_type="pdf",
            page_count=1,
            page_dimensions=[(100, 100)],
            has_text_layer=True,
            appears_image_only=False,
            requires_ocr=False,
        ),
        document_ir=None,
        text_source="native",
        template_match=TemplateMatch(
            template_id="UNKNOWN",
            version=None,
            confidence=0.0,
            evidence=TemplateMatchEvidence(),
            warnings=[],
            requires_review=True,
        ),
        diagram=None,
        narrative=None,
        qa=qa,
    )


def test_exporter_writes_nothing_when_blocked(tmp_path: Path) -> None:
    qa = QAReport(
        export_decision="BLOCK",
        export_blocked=True,
        blocking_reasons=["unit-test forced block"],
        qa_flags=["TEMPLATE_UNKNOWN"],
        requires_human_review=True,
    )
    artifact = _artifact_with_qa(qa)
    out_dir = tmp_path / "exports"
    work_dir = tmp_path / "work"

    result = export_artifact(
        artifact,
        pii_entities_pages=[],
        pii_entities_narrative=[],
        source_image_paths={},
        export_dir=out_dir,
        work_dir=work_dir,
        config=AppConfig(),
    )

    assert result.skipped is True
    assert result.written == []
    # Critical: no directory or file may be created.
    assert not (out_dir / f"report_{artifact.file_entry.sha256[:16]}").exists()


def test_exporter_skip_reason_includes_qa_blocking_reasons(tmp_path: Path) -> None:
    qa = QAReport(
        export_decision="BLOCK",
        export_blocked=True,
        blocking_reasons=["foo missing", "bar uncertain"],
        qa_flags=["TEMPLATE_UNKNOWN"],
        requires_human_review=True,
    )
    result = export_artifact(
        _artifact_with_qa(qa),
        pii_entities_pages=[],
        pii_entities_narrative=[],
        source_image_paths={},
        export_dir=tmp_path / "exports",
        work_dir=tmp_path / "work",
        config=AppConfig(),
    )
    assert "foo missing" in (result.skip_reason or "")
    assert "bar uncertain" in (result.skip_reason or "")
