"""Phase 4 integration tests — PII + redaction + public export.

End-to-end happy path uses the OCR text path with mock_tokens that carry
synthetic PII (so word-level bboxes from mock_ocr exist and entities can
be mapped to image coordinates). The native-text path with PII is also
exercised to verify that the pipeline correctly fails closed when bboxes
cannot be derived.
"""
from __future__ import annotations

import json
from pathlib import Path

from care.core.config import AppConfig
from care.workers.pipeline import run_pipeline
from tests._fixtures import (
    make_example_template_pdf,
    make_synthetic_image,
    make_unknown_template_pdf,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TEMPLATES_DIR = REPO_ROOT / "templates"

PII_TOKENS = [
    "Example", "Crash", "Report",
    "Form:", "EX-CR-99",
    "Diagram",
    "Narrative",
    "Driver", "JOHN", "DOE", "at", "555-123-4567",
    "VIN:", "1HGCM82633A004352",
    "Officer",
]


def _config_for(tmp_path: Path, *, mock_tokens: list[str] | None = None) -> AppConfig:
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    cfg.paths.export_dir = str(tmp_path / "exports")
    cfg.paths.templates_dir = str(EXAMPLE_TEMPLATES_DIR)
    if mock_tokens is not None:
        cfg.ocr.providers = {"mock_ocr": {"mock_tokens": mock_tokens}}
    return cfg


def test_phase4_happy_path_writes_five_redacted_files(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")

    cfg = _config_for(tmp_path, mock_tokens=PII_TOKENS)
    result = run_pipeline(inputs, config=cfg)
    artifact = result.artifacts[0]

    assert artifact.template_match.template_id == "example_state_crash_v1"
    assert artifact.qa.export_decision == "ALLOW"
    assert artifact.export_blocked is False

    out_dir = Path(artifact.export_result.output_dir)
    expected = {
        "diagram.redacted.png",
        "narrative.redacted.txt",
        "narrative.redacted.json",
        "manifest.json",
        "qa.json",
    }
    actual = {p.name for p in out_dir.iterdir()}
    assert actual == expected

    # Redacted narrative contains placeholders, no raw PII tokens.
    redacted_text = (out_dir / "narrative.redacted.txt").read_text(encoding="utf-8")
    assert "[PERSON_NAME]" in redacted_text
    assert "[PHONE_NUMBER]" in redacted_text
    assert "[VIN]" in redacted_text
    for raw in ("JOHN", "DOE", "555-123-4567", "1HGCM82633A004352"):
        assert raw not in redacted_text, f"raw PII '{raw}' leaked into narrative.redacted.txt"

    # narrative.redacted.json mirrors the redacted text and never carries raw PII.
    payload = json.loads((out_dir / "narrative.redacted.json").read_text(encoding="utf-8"))
    assert payload["text"] == redacted_text
    for raw in ("JOHN", "DOE", "555-123-4567", "1HGCM82633A004352"):
        assert raw not in json.dumps(payload), f"raw PII '{raw}' leaked into narrative.redacted.json"
    # Audit trail records entity types and offsets but not text values.
    for entry in payload["entities_redacted"]:
        assert "text" not in entry
        assert "entity_type" in entry

    # manifest.json declares the export is safe.
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["export_contains_original_pdf"] is False
    assert manifest["export_contains_unredacted_text"] is False
    assert manifest["export_contains_raw_ocr_or_vlm_output"] is False
    assert manifest["template_id"] == "example_state_crash_v1"
    assert manifest["pii_provider_chain"] == ["regex"]

    # qa.json contains the QA report.
    qa = json.loads((out_dir / "qa.json").read_text(encoding="utf-8"))
    assert qa["export_decision"] == "ALLOW"
    assert qa["export_blocked"] is False


def test_phase5_native_text_with_pii_redacts_via_image_bboxes(tmp_path: Path) -> None:
    """Phase 5: native PDF text now carries image-space charbox-derived bboxes,
    so PII detected in the native text can be mapped to image coordinates and
    safely redacted. Export should ALLOW and the redacted artifacts should not
    leak the raw PII tokens."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_example_template_pdf(
        inputs / "with_pii.pdf",
        narrative_body="Phone 555-123-4567 and VIN 1HGCM82633A004352 here.",
        officer_line="Officer",
    )

    cfg = _config_for(tmp_path)
    result = run_pipeline(inputs, config=cfg)
    artifact = result.artifacts[0]

    assert artifact.template_match.template_id == "example_state_crash_v1"
    assert artifact.text_source == "native"
    assert artifact.qa.export_decision == "ALLOW"
    assert artifact.export_blocked is False
    # PII_UNMAPPED must NOT appear — every entity has an image-space bbox.
    assert "PII_UNMAPPED" not in artifact.qa.qa_flags
    assert artifact.qa.pii_unmapped_count == 0
    assert artifact.qa.pii_entity_count >= 2  # phone + vin

    out_dir = Path(artifact.export_result.output_dir)
    redacted_text = (out_dir / "narrative.redacted.txt").read_text(encoding="utf-8")
    for raw in ("555-123-4567", "1HGCM82633A004352"):
        assert raw not in redacted_text, f"raw PII '{raw}' leaked into redacted text"
    assert "[PHONE_NUMBER]" in redacted_text
    assert "[VIN]" in redacted_text


def test_phase4_unknown_template_blocks_export(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_unknown_template_pdf(inputs / "random.pdf")
    cfg = _config_for(tmp_path)
    result = run_pipeline(inputs, config=cfg)
    artifact = result.artifacts[0]
    assert artifact.qa.export_blocked is True
    assert artifact.export_result.skipped is True
    export_dir = Path(cfg.paths.export_dir)
    if export_dir.exists():
        assert list(export_dir.rglob("*")) == []


def test_phase4_export_directory_never_contains_source_pdf(tmp_path: Path) -> None:
    """Even on the happy path, the exporter must never copy the source file."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")

    cfg = _config_for(tmp_path, mock_tokens=PII_TOKENS)
    run_pipeline(inputs, config=cfg)

    export_dir = Path(cfg.paths.export_dir)
    leaked_pdf = list(export_dir.rglob("*.pdf"))
    leaked_images = [p for p in export_dir.rglob("*") if p.suffix in {".jpg", ".jpeg", ".tif", ".tiff"}]
    leaked_source = list(export_dir.rglob("scan.png"))
    assert leaked_pdf == []
    assert leaked_images == []
    assert leaked_source == []


def test_phase4_export_artifact_files_have_redacted_in_name(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")
    cfg = _config_for(tmp_path, mock_tokens=PII_TOKENS)
    result = run_pipeline(inputs, config=cfg)
    out_dir = Path(result.artifacts[0].export_result.output_dir)
    image_files = [p.name for p in out_dir.glob("*.png")]
    assert image_files == ["diagram.redacted.png"]


def test_phase4_diagram_redacted_image_is_valid_png(tmp_path: Path) -> None:
    from PIL import Image

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")
    cfg = _config_for(tmp_path, mock_tokens=PII_TOKENS)
    result = run_pipeline(inputs, config=cfg)
    diagram_path = Path(result.artifacts[0].export_result.output_dir) / "diagram.redacted.png"
    assert diagram_path.exists()
    with Image.open(diagram_path) as img:
        assert img.format == "PNG"
        assert img.size[0] > 0 and img.size[1] > 0
