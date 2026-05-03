"""Phase 3 pipeline integration tests.

Verifies template detection, diagram + narrative extraction, and the
QA fail-closed gate. Phase 4 (PII detection + redaction + export) is
also exercised here for end-to-end determinism.
"""
from __future__ import annotations

from pathlib import Path

from care.core.config import AppConfig
from care.workers.pipeline import PipelineRunResult, run_pipeline
from tests._fixtures import (
    make_example_template_pdf,
    make_synthetic_image,
    make_unknown_template_pdf,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TEMPLATES_DIR = REPO_ROOT / "templates"


def _config_for(tmp_path: Path) -> AppConfig:
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    cfg.paths.export_dir = str(tmp_path / "exports")
    cfg.paths.templates_dir = str(EXAMPLE_TEMPLATES_DIR)
    return cfg


def test_pipeline_matches_example_template_and_qa_allows(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_example_template_pdf(inputs / "ex.pdf")

    result: PipelineRunResult = run_pipeline(inputs, config=_config_for(tmp_path))
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]

    assert artifact.template_match.template_id == "example_state_crash_v1"
    assert artifact.template_match.confidence >= 0.85
    assert artifact.template_match.requires_review is False

    assert artifact.diagram is not None
    assert artifact.diagram.image_path is not None
    assert Path(artifact.diagram.image_path).exists()
    assert artifact.diagram.confidence >= 0.85
    assert artifact.diagram.requires_review is False

    assert artifact.narrative is not None
    assert "Vehicle" in artifact.narrative.text
    assert "Officer" not in artifact.narrative.text  # end-anchor stripped
    assert artifact.narrative.confidence >= 0.85
    assert artifact.narrative.requires_review is False

    qa = artifact.qa
    assert qa.export_decision == "ALLOW"
    assert qa.export_blocked is False
    assert qa.blocking_reasons == []
    assert qa.requires_human_review is False
    assert artifact.export_blocked is False  # Phase 4 exporter wrote the artifacts


def test_pipeline_blocks_export_for_unknown_template(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_unknown_template_pdf(inputs / "random.pdf")

    result = run_pipeline(inputs, config=_config_for(tmp_path))
    artifact = result.artifacts[0]

    assert artifact.template_match.template_id == "UNKNOWN"
    assert artifact.template_match.requires_review is True
    assert artifact.diagram is None
    assert artifact.narrative is None

    qa = artifact.qa
    assert qa.export_decision == "BLOCK"
    assert qa.export_blocked is True
    assert "TEMPLATE_UNKNOWN" in qa.qa_flags
    assert "TEMPLATE_LOW_CONFIDENCE" in qa.qa_flags
    assert qa.requires_human_review is True
    assert any("UNKNOWN" in r for r in qa.blocking_reasons)
    assert artifact.export_blocked is True


def test_pipeline_blocks_when_no_templates_registered(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_example_template_pdf(inputs / "ex.pdf")

    cfg = _config_for(tmp_path)
    cfg.paths.templates_dir = str(tmp_path / "no_templates_here")

    result = run_pipeline(inputs, config=cfg)
    artifact = result.artifacts[0]
    assert artifact.template_match.template_id == "UNKNOWN"
    assert artifact.qa.export_decision == "BLOCK"
    assert "TEMPLATE_UNKNOWN" in artifact.qa.qa_flags


def test_pipeline_blocks_image_input_no_anchors(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")  # mock OCR returns "MOCK", "REPORT"

    result = run_pipeline(inputs, config=_config_for(tmp_path))
    artifact = result.artifacts[0]
    # Mock OCR text "MOCK REPORT" doesn't satisfy the example template anchors.
    assert artifact.template_match.template_id == "UNKNOWN"
    assert artifact.qa.export_blocked is True


def test_pipeline_runs_template_detection_on_ocr_path(tmp_path: Path) -> None:
    """When mock OCR is configured to emit anchors, the template should match."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")

    cfg = _config_for(tmp_path)
    cfg.ocr.providers = {
        "mock_ocr": {
            "mock_tokens": [
                "Example", "Crash", "Report",
                "Form:", "EX-CR-99",
                "Diagram",
                "Narrative",
                "Vehicle", "A", "traveling", "north",
                "Officer",
            ]
        }
    }

    result = run_pipeline(inputs, config=cfg)
    artifact = result.artifacts[0]
    assert artifact.text_source == "ocr"
    assert artifact.template_match.template_id == "example_state_crash_v1"
    assert artifact.diagram is not None
    assert artifact.narrative is not None
    assert artifact.qa.export_decision == "ALLOW"


def test_pipeline_does_not_export_when_template_is_unknown(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_unknown_template_pdf(inputs / "random.pdf")

    cfg = _config_for(tmp_path)
    run_pipeline(inputs, config=cfg)

    export_dir = Path(cfg.paths.export_dir)
    if export_dir.exists():
        leaked = list(export_dir.rglob("*"))
        assert leaked == [], f"Unexpected files in export dir for blocked report: {leaked}"
