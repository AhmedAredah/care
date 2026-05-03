"""Phase 5 integration tests — VLM/document-AI reconciliation in the pipeline."""
from __future__ import annotations

from pathlib import Path

from care.core.config import AppConfig
from care.workers.pipeline import run_pipeline
from tests._fixtures import make_synthetic_image

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TEMPLATES_DIR = REPO_ROOT / "templates"


def _vlm_config(tmp_path: Path, *, mock_mode: str = "default") -> AppConfig:
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    cfg.paths.export_dir = str(tmp_path / "exports")
    cfg.paths.templates_dir = str(EXAMPLE_TEMPLATES_DIR)
    cfg.document_ai.enabled = True
    cfg.document_ai.provider_chain = ["mock_vlm"]
    cfg.document_ai.providers = {"mock_vlm": {"mock_mode": mock_mode}}
    return cfg


def test_phase5_pipeline_runs_without_vlm_by_default(tmp_path: Path) -> None:
    """document_ai.enabled defaults to False — the pipeline must not invoke
    any VLM provider and produce no VLM warnings."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")

    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    cfg.paths.export_dir = str(tmp_path / "exports")
    cfg.paths.templates_dir = str(EXAMPLE_TEMPLATES_DIR)
    result = run_pipeline(inputs, config=cfg)
    artifact = result.artifacts[0]
    assert artifact.vlm_warnings == []
    # No VLM-derived QA flag should appear.
    for flag in artifact.qa.qa_flags:
        assert not flag.startswith("VLM_")


def test_phase5_no_bboxes_mode_emits_vlm_no_bbox_warning(tmp_path: Path) -> None:
    """When the VLM emits text without bboxes, reconciliation must record
    VLM_OUTPUT_HAS_NO_BBOXES — the alt words MUST NOT enter base words'
    alternative_sources, so image redaction stays driven by OCR-only bboxes."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")

    cfg = _vlm_config(tmp_path, mock_mode="no_bboxes")
    result = run_pipeline(inputs, config=cfg)
    artifact = result.artifacts[0]

    codes = {w.code for w in artifact.vlm_warnings}
    assert "VLM_OUTPUT_HAS_NO_BBOXES" in codes
    # Generative model: review-required flag also fires.
    assert "VLM_GENERATIVE_OUTPUT_REQUIRES_REVIEW" in codes
    # No alternative_sources were attached anywhere — VLM-only-without-bboxes
    # must never drive image redaction.
    for page in artifact.document_ir.pages:
        for w in page.words:
            assert w.alternative_sources == []


def test_phase5_conflict_mode_blocks_export(tmp_path: Path) -> None:
    """When a VLM disagrees with OCR at the same bbox, qa.export_decision
    must be BLOCK and VLM_OUTPUT_CONFLICTS_WITH_OCR is in qa_flags."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")

    cfg = _vlm_config(tmp_path, mock_mode="conflict_with_ocr")
    # Use mock OCR tokens that line up with the conflict_with_ocr VLM bboxes
    # (those are at x=0..60 and x=65..150 — the default mock_ocr layout).
    cfg.ocr.providers = {"mock_ocr": {"mock_tokens": ["MOCK", "REPORT"]}}
    result = run_pipeline(inputs, config=cfg)
    artifact = result.artifacts[0]

    assert "VLM_OUTPUT_CONFLICTS_WITH_OCR" in artifact.qa.qa_flags
    assert artifact.qa.export_decision == "BLOCK"
    assert artifact.qa.requires_human_review is True
    # No public artifacts written.
    export_dir = Path(cfg.paths.export_dir)
    if export_dir.exists():
        assert list(export_dir.rglob("*")) == []


def test_phase5_default_mode_records_vlm_used_for_extraction(tmp_path: Path) -> None:
    """In the no-conflict default mode, VLM_USED_FOR_EXTRACTION must still
    be recorded so downstream auditors know a generative source contributed."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")
    cfg = _vlm_config(tmp_path, mock_mode="default")
    cfg.ocr.providers = {"mock_ocr": {"mock_tokens": ["MOCK", "REPORT"]}}
    result = run_pipeline(inputs, config=cfg)
    artifact = result.artifacts[0]
    codes = {w.code for w in artifact.vlm_warnings}
    assert "VLM_USED_FOR_EXTRACTION" in codes


def test_phase5_pipeline_records_ocr_provider_used(tmp_path: Path) -> None:
    """The pipeline must record which OCR provider succeeded so the manifest
    can audit whether mock_ocr / paddleocr / tesseract handled the page."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    cfg.paths.export_dir = str(tmp_path / "exports")
    cfg.paths.templates_dir = str(EXAMPLE_TEMPLATES_DIR)
    result = run_pipeline(inputs, config=cfg)
    artifact = result.artifacts[0]
    assert artifact.ocr_provider_used == "mock_ocr"
