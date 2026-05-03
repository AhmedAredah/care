"""End-to-end tests for the API job + report flow (Phase 6).

These tests run the full pipeline through the API runner, then exercise
every report endpoint against the produced reports. No httpx required —
handlers are called as plain functions.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from care.api.routes_exports import list_exports
from care.api.routes_jobs import JobSubmission, get_job, list_jobs, submit_job
from care.api.routes_reports import (
    get_report,
    get_report_diagram,
    get_report_manifest,
    get_report_narrative,
    get_report_qa,
)
from care.api.routes_review import ReviewBody, approve_report, reject_report
from care.core.config import AppConfig
from care.services.jobs import JobStore
from tests._fixtures import make_synthetic_image

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


def _config(tmp_path: Path) -> AppConfig:
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    cfg.paths.export_dir = str(tmp_path / "exports")
    cfg.paths.templates_dir = str(EXAMPLE_TEMPLATES_DIR)
    cfg.ocr.providers = {"mock_ocr": {"mock_tokens": PII_TOKENS}}
    return cfg


def _allowed_setup(tmp_path: Path) -> tuple[JobStore, AppConfig, str]:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")
    cfg = _config(tmp_path)
    store = JobStore()
    body = JobSubmission(input_dir=str(inputs.resolve()))
    record = submit_job(body, config=cfg, store=store)
    assert record["status"] == "complete"
    assert record["report_ids"], "expected at least one report id"
    return store, cfg, record["report_ids"][0]


def test_submit_job_runs_pipeline_and_registers_reports(tmp_path: Path) -> None:
    store, _cfg, report_id = _allowed_setup(tmp_path)
    assert len(report_id) == 16
    jobs = list_jobs(store=store)["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["status"] == "complete"
    assert report_id in jobs[0]["report_ids"]


def test_submit_job_rejects_relative_path(tmp_path: Path) -> None:
    store = JobStore()
    body = JobSubmission(input_dir="relative/path")
    with pytest.raises(HTTPException) as ei:
        submit_job(body, config=AppConfig(), store=store)
    assert ei.value.status_code == 400


def test_submit_job_rejects_missing_dir(tmp_path: Path) -> None:
    store = JobStore()
    body = JobSubmission(input_dir=str(tmp_path / "no_such_dir"))
    with pytest.raises(HTTPException) as ei:
        submit_job(body, config=AppConfig(), store=store)
    assert ei.value.status_code == 404


def test_get_job_returns_404_for_unknown_id() -> None:
    store = JobStore()
    with pytest.raises(HTTPException) as ei:
        get_job("doesnotexist", store=store)
    assert ei.value.status_code == 404


def test_get_report_returns_view_without_raw_pii_or_paths(tmp_path: Path) -> None:
    store, _cfg, report_id = _allowed_setup(tmp_path)
    payload = get_report(report_id, store=store)
    # Sanity / non-leak checks.
    for key in ("words", "ocr_words", "vlm_text", "raw_text", "input_dir"):
        assert key not in payload, f"unsafe key {key!r} leaked in report view"
    assert payload["report_id"] == report_id
    assert payload["template_id"] == "example_state_crash_v1"
    # Raw PII tokens must NOT appear anywhere in the JSON-able view.
    blob = repr(payload)
    for raw in ("JOHN", "DOE", "555-123-4567", "1HGCM82633A004352"):
        assert raw not in blob, f"raw PII '{raw}' leaked into report view"


def test_get_report_rejects_invalid_id_shape() -> None:
    store = JobStore()
    for bad in ("../etc/passwd", "../../foo", "x" * 32, "xyz", ""):
        with pytest.raises(HTTPException) as ei:
            get_report(bad, store=store)
        assert ei.value.status_code in (400, 404)


def test_get_report_diagram_serves_only_redacted_png(tmp_path: Path) -> None:
    store, cfg, report_id = _allowed_setup(tmp_path)
    response = get_report_diagram(report_id, store=store, config=cfg)
    assert isinstance(response, FileResponse)
    assert str(response.path).endswith("diagram.redacted.png")
    # The served file must live under the configured export_dir.
    served = Path(response.path).resolve()
    export_root = Path(cfg.paths.export_dir).resolve()
    served.relative_to(export_root)


def test_get_report_narrative_returns_redacted_payload(tmp_path: Path) -> None:
    store, cfg, report_id = _allowed_setup(tmp_path)
    response = get_report_narrative(report_id, store=store, config=cfg)
    assert isinstance(response, JSONResponse)
    body = response.body.decode("utf-8")
    for raw in ("JOHN", "DOE", "555-123-4567", "1HGCM82633A004352"):
        assert raw not in body
    assert "[PERSON_NAME]" in body
    assert "[PHONE_NUMBER]" in body
    assert "[VIN]" in body


def test_get_report_narrative_text_format(tmp_path: Path) -> None:
    store, cfg, report_id = _allowed_setup(tmp_path)
    response = get_report_narrative(
        report_id, store=store, config=cfg, format="text"
    )
    assert isinstance(response, PlainTextResponse)
    text = response.body.decode("utf-8")
    for raw in ("JOHN", "DOE", "555-123-4567", "1HGCM82633A004352"):
        assert raw not in text


def test_get_report_qa_synthesizes_when_blocked(tmp_path: Path) -> None:
    """Reports that the QA gate blocked have no on-disk qa.json — the
    handler must synthesize the response from the in-memory view."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    # Use mock_tokens that won't satisfy any template → unknown template
    # → export blocked.
    make_synthetic_image(inputs / "scan.png")
    cfg = _config(tmp_path)
    cfg.ocr.providers = {"mock_ocr": {"mock_tokens": ["X"]}}
    store = JobStore()
    record = submit_job(
        JobSubmission(input_dir=str(inputs.resolve())),
        config=cfg,
        store=store,
    )
    report_id = record["report_ids"][0]
    response = get_report_qa(report_id, store=store, config=cfg)
    body = response.body.decode("utf-8")
    assert "BLOCK" in body
    assert "TEMPLATE_UNKNOWN" in body
    # manifest endpoint must refuse to serve a manifest for blocked reports.
    with pytest.raises(HTTPException) as ei:
        get_report_manifest(report_id, store=store, config=cfg)
    assert ei.value.status_code == 409
    # diagram and narrative likewise.
    with pytest.raises(HTTPException) as ei:
        get_report_diagram(report_id, store=store, config=cfg)
    assert ei.value.status_code == 409
    with pytest.raises(HTTPException) as ei:
        get_report_narrative(report_id, store=store, config=cfg)
    assert ei.value.status_code == 409


def test_list_exports_only_lists_report_dirs(tmp_path: Path) -> None:
    store, cfg, report_id = _allowed_setup(tmp_path)
    # Drop a stray file beside the export dir; it must not appear in
    # the exports listing.
    export_root = Path(cfg.paths.export_dir)
    (export_root / "stray.txt").write_text("nope")
    payload = list_exports(config=cfg)
    assert any(r["report_id"] == report_id for r in payload["reports"])
    listed_files = {f for r in payload["reports"] for f in r["files"]}
    assert "stray.txt" not in listed_files
    # Only the five expected redacted files are listed.
    assert listed_files <= {
        "diagram.redacted.png",
        "narrative.redacted.txt",
        "narrative.redacted.json",
        "manifest.json",
        "qa.json",
    }


def test_review_approve_updates_state_for_allowed_report(tmp_path: Path) -> None:
    store, cfg, report_id = _allowed_setup(tmp_path)
    out = approve_report(
        report_id,
        ReviewBody(reviewer="alice", notes="LGTM"),
        store=store,
    )
    assert out["review"]["decision"] == "APPROVED"
    assert out["review"]["reviewer"] == "alice"
    # Reading the report again reflects the new state.
    refreshed = get_report(report_id, store=store)
    assert refreshed["review"]["decision"] == "APPROVED"


def test_review_approve_refuses_when_qa_blocked(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")
    cfg = _config(tmp_path)
    cfg.ocr.providers = {"mock_ocr": {"mock_tokens": ["X"]}}  # unknown template
    store = JobStore()
    record = submit_job(
        JobSubmission(input_dir=str(inputs.resolve())),
        config=cfg,
        store=store,
    )
    report_id = record["report_ids"][0]
    with pytest.raises(HTTPException) as ei:
        approve_report(
            report_id, ReviewBody(reviewer="alice"), store=store
        )
    assert ei.value.status_code == 409
    # Reject is allowed even when blocked.
    out = reject_report(
        report_id, ReviewBody(reviewer="alice"), store=store
    )
    assert out["review"]["decision"] == "REJECTED"


def test_review_unknown_report_returns_404() -> None:
    store = JobStore()
    with pytest.raises(HTTPException) as ei:
        approve_report("0123456789abcdef", ReviewBody(), store=store)
    assert ei.value.status_code == 404
