"""Path-traversal and file-exposure tests for report endpoints (Phase 6)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from care.api.routes_reports import (
    REPORT_ID_RE,
    _resolve_export_subpath,
    _validate_report_id,
)
from care.core.config import AppConfig
from care.services.jobs import ReportView


def _view(report_id: str = "0123456789abcdef") -> ReportView:
    return ReportView(
        report_id=report_id,
        source_sha256=report_id + "0" * (64 - len(report_id)),
        source_file_name="x.png",
        file_type="image",
        template_id="example_state_crash_v1",
        template_version="1.0",
        template_confidence=0.95,
        text_source="ocr",
        ocr_provider_used="mock_ocr",
        qa_decision="ALLOW",
        qa_export_blocked=False,
        qa_flags=[],
        qa_blocking_reasons=[],
        qa_requires_human_review=False,
        qa_pii_entity_count=0,
        qa_pii_unmapped_count=0,
        diagram_confidence=0.9,
        narrative_confidence=0.9,
        export_dir="/tmp/exports",
    )


def test_report_id_regex_matches_only_16_hex_chars() -> None:
    assert REPORT_ID_RE.fullmatch("0123456789abcdef")
    assert not REPORT_ID_RE.fullmatch("0123456789ABCDEF")  # case-sensitive
    assert not REPORT_ID_RE.fullmatch("0123456789abcde")  # too short
    assert not REPORT_ID_RE.fullmatch("../0123456789abc")
    assert not REPORT_ID_RE.fullmatch("g123456789abcdef")  # non-hex


def test_validate_report_id_raises_400_for_invalid_inputs() -> None:
    for bad in [
        "../etc/passwd",
        "..",
        "0123",
        "0123456789abcde/",
        "0123456789abcdef ",
        "0123456789abcdef/extra",
    ]:
        with pytest.raises(HTTPException) as ei:
            _validate_report_id(bad)
        assert ei.value.status_code == 400


def test_resolve_export_subpath_blocks_traversal(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.paths.export_dir = str(tmp_path / "exports")
    Path(cfg.paths.export_dir).mkdir()
    view = _view()

    # Create a file OUTSIDE the export dir; the handler must refuse to serve it.
    outside = tmp_path / "secret.txt"
    outside.write_text("super secret")

    # Even if the report_id and the report dir name are valid, traversal
    # via "../" must be caught by safe_join → 400.
    with pytest.raises(HTTPException) as ei:
        _resolve_export_subpath(cfg, view, "..", "..", "secret.txt")
    assert ei.value.status_code == 400


def test_resolve_export_subpath_404_when_file_missing(tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.paths.export_dir = str(tmp_path / "exports")
    Path(cfg.paths.export_dir).mkdir()
    view = _view()

    # Create the report dir but not the file.
    report_dir = Path(cfg.paths.export_dir) / f"report_{view.report_id}"
    report_dir.mkdir()
    with pytest.raises(HTTPException) as ei:
        _resolve_export_subpath(cfg, view, "qa.json")
    assert ei.value.status_code == 404
