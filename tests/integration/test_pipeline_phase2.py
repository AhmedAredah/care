"""End-to-end Phase 2 pipeline tests.

Pipeline branches verified:
- Image input  → render passthrough → mock OCR → DocumentIR (text_source=ocr)
- Digital PDF  → native text → DocumentIR (text_source=native)
- Image-only PDF → render → mock OCR → DocumentIR (text_source=ocr)

Every artifact must arrive with `export_blocked=True` since template
detection / extraction / redaction / export land in Phase 3+.
"""
from __future__ import annotations

from pathlib import Path

from care.core.config import AppConfig
from care.workers.pipeline import (
    PipelineRunResult,
    ReportArtifact,
    run_pipeline,
)
from tests._fixtures import (
    make_digital_pdf,
    make_image_only_pdf,
    make_mixed_pdf,
    make_synthetic_image,
)


def _config_for(tmp_path: Path) -> AppConfig:
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    cfg.paths.export_dir = str(tmp_path / "exports")
    return cfg


def test_pipeline_processes_image_via_mock_ocr(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")

    result = run_pipeline(inputs, config=_config_for(tmp_path))

    assert isinstance(result, PipelineRunResult)
    assert len(result.file_entries) == 1
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert isinstance(artifact, ReportArtifact)
    assert artifact.text_source == "ocr"
    assert artifact.document_ir.file_type == "image"
    assert artifact.document_ir.pages[0].text_source == "ocr"
    # Mock OCR emits "MOCK" / "REPORT".
    words = [w.text for w in artifact.document_ir.pages[0].words]
    assert words == ["MOCK", "REPORT"]
    # Mock OCR text "MOCK REPORT" doesn't satisfy any registered template,
    # so the QA gate blocks export.
    assert artifact.export_blocked is True
    assert "TEMPLATE_UNKNOWN" in artifact.qa.qa_flags


def test_pipeline_uses_native_text_for_digital_pdf(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_digital_pdf(
        inputs / "digital.pdf",
        lines=["MOCK CRASH REPORT", "Officer Synthetic Test Only"],
    )

    result = run_pipeline(inputs, config=_config_for(tmp_path))
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.text_source == "native"
    assert artifact.document_ir.file_type == "pdf"
    page = artifact.document_ir.pages[0]
    assert page.text_source == "native"
    text = " ".join(w.text for w in page.words)
    assert "MOCK" in text
    assert "REPORT" in text
    # Phase 5: native text-layer words now carry image-space char-derived bboxes
    # (in pixel coordinates of the rendered page at DEFAULT_RENDER_DPI), so
    # they CAN drive image redaction.
    assert any(w.can_map_to_image_coordinates for w in page.words)
    assert all(
        (w.bbox is None) or (len(w.bbox) == 4 and w.bbox[2] > w.bbox[0])
        for w in page.words
    )
    assert artifact.export_blocked is True


def test_pipeline_falls_back_to_ocr_for_image_only_pdf(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    img = make_synthetic_image(tmp_path / "scratch.png")
    make_image_only_pdf(inputs / "scanned.pdf", image_path=img)

    result = run_pipeline(inputs, config=_config_for(tmp_path))
    artifact = result.artifacts[0]
    assert artifact.inspection.has_text_layer is False
    assert artifact.text_source == "ocr"
    assert artifact.document_ir.pages[0].text_source == "ocr"
    assert artifact.work_dir is not None
    assert Path(artifact.work_dir).is_dir()


def test_pipeline_routes_mixed_pdf_per_page(tmp_path: Path) -> None:
    """A single PDF whose page 0 has native text and page 1 is a
    rasterized image must be routed page-by-page: page 0 native, page
    1 OCR. This was the silent data-loss bug under the previous
    document-level routing — the whole PDF took the native path and
    page 1 emitted no words.
    """
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    img = make_synthetic_image(tmp_path / "scratch.png")
    make_mixed_pdf(inputs / "mixed.pdf", image_path=img)

    result = run_pipeline(inputs, config=_config_for(tmp_path))
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]

    # Document-level summary surfaces the mixed shape so the GUI /
    # manifest can show it explicitly.
    assert artifact.text_source == "mixed"
    assert artifact.inspection.page_has_text == [True, False]
    assert artifact.inspection.has_text_layer is True

    pages = artifact.document_ir.pages
    assert len(pages) == 2
    assert pages[0].text_source == "native"
    assert pages[1].text_source == "ocr"

    # Page 0 carries the typed narrative.
    p0_text = " ".join(w.text for w in pages[0].words)
    assert "MOCK" in p0_text
    assert "REPORT" in p0_text

    # Page 1 carries the mock OCR output rather than being silently
    # blank. Mock OCR emits "MOCK"/"REPORT" — the proof point is that
    # SOME words were produced and they came from a traditional OCR
    # provider, not from the native_pdf source.
    assert pages[1].words, "page 1 must not be silently empty"
    assert all(w.source != "native_pdf" for w in pages[1].words)
    assert all(w.source_provider_type == "traditional_ocr" for w in pages[1].words)


def test_pipeline_processes_mixed_directory(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")
    make_digital_pdf(inputs / "digital.pdf")

    result = run_pipeline(inputs, config=_config_for(tmp_path))
    assert len(result.artifacts) == 2
    sources = {a.text_source for a in result.artifacts}
    assert sources == {"ocr", "native"}
    # Every artifact is fail-closed.
    assert all(a.export_blocked for a in result.artifacts)


def test_pipeline_does_not_modify_source_files(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    src = make_synthetic_image(inputs / "scan.png")
    before = src.read_bytes()
    before_mtime = src.stat().st_mtime

    run_pipeline(inputs, config=_config_for(tmp_path))

    after = src.read_bytes()
    assert before == after
    assert src.stat().st_mtime == before_mtime


def test_pipeline_documentir_round_trips_to_json(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")
    result = run_pipeline(inputs, config=_config_for(tmp_path))

    from care.document_ir import from_json, to_json

    payload = to_json(result.artifacts[0].document_ir)
    parsed = from_json(payload)
    assert parsed == result.artifacts[0].document_ir
