"""Per-job template allowlist (jurisdiction / template_ids).

These tests verify the route end to end: submitting a job with a filter
narrows the candidate template set inside the pipeline. The default
example template lives under ``templates/`` with
``jurisdiction == "EXAMPLE"`` and ``template_id == "example_state_crash_v1"``,
so we can exercise both match and miss paths against the real registry
without having to author another fixture template.
"""
from __future__ import annotations

from pathlib import Path

from care.api.routes_jobs import JobSubmission, submit_job
from care.core.config import AppConfig
from care.services.jobs import JobStore
from tests._fixtures import make_synthetic_image

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_TEMPLATES_DIR = REPO_ROOT / "templates"
EXAMPLE_TEMPLATE_ID = "example_state_crash_v1"
EXAMPLE_JURISDICTION = "EXAMPLE"

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


def _inputs(tmp_path: Path) -> Path:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")
    return inputs


def test_no_filter_records_no_audit_field(tmp_path: Path) -> None:
    """When jurisdiction and template_ids are both omitted, the
    JobRecord's template_filter stays None — so jobs that don't care
    about scoping aren't cluttered with audit metadata."""
    cfg = _config(tmp_path)
    store = JobStore()
    body = JobSubmission(input_dir=str(_inputs(tmp_path).resolve()))
    record = submit_job(body, config=cfg, store=store)
    assert record["template_filter"] is None


def test_jurisdiction_filter_matches_example_template(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    store = JobStore()
    body = JobSubmission(
        input_dir=str(_inputs(tmp_path).resolve()),
        jurisdiction=EXAMPLE_JURISDICTION,
    )
    record = submit_job(body, config=cfg, store=store)
    assert record["status"] == "complete"
    audit = record["template_filter"]
    assert audit is not None
    assert audit["jurisdiction"] == EXAMPLE_JURISDICTION
    assert audit["matched_template_ids"] == [EXAMPLE_TEMPLATE_ID]


def test_template_ids_filter_matches_example_template(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    store = JobStore()
    body = JobSubmission(
        input_dir=str(_inputs(tmp_path).resolve()),
        template_ids=[EXAMPLE_TEMPLATE_ID, "ghost_template_does_not_exist"],
    )
    record = submit_job(body, config=cfg, store=store)
    assert record["status"] == "complete"
    audit = record["template_filter"]
    assert audit is not None
    assert audit["matched_template_ids"] == [EXAMPLE_TEMPLATE_ID]


def test_unmatched_jurisdiction_filter_yields_unknown_template(tmp_path: Path) -> None:
    """A jurisdiction the operator typed but no template carries should
    fail closed — every report comes back as TEMPLATE_UNKNOWN. This is
    intentional: a non-empty but unmatched allowlist should NOT silently
    fall back to "use all templates"."""
    from care.services.jobs import JobStore as Store  # local alias

    cfg = _config(tmp_path)
    store = Store()
    body = JobSubmission(
        input_dir=str(_inputs(tmp_path).resolve()),
        jurisdiction="not_a_real_state",
    )
    record = submit_job(body, config=cfg, store=store)
    assert record["status"] == "complete"
    audit = record["template_filter"]
    assert audit is not None
    assert audit["matched_template_ids"] == []
    assert record["report_ids"], "pipeline still runs; reports just block"
    view = store.get_report(record["report_ids"][0])
    assert view is not None
    assert view.template_id == "UNKNOWN"
    assert view.qa_export_blocked is True


def test_empty_template_ids_list_treated_as_no_filter(tmp_path: Path) -> None:
    """Operator submits an empty list (e.g. the GUI input was blank).
    That MUST behave identically to omitting the field — i.e. all
    templates are considered. Without this, a stray empty list would
    silently disable all matching."""
    cfg = _config(tmp_path)
    store = JobStore()
    body = JobSubmission(
        input_dir=str(_inputs(tmp_path).resolve()),
        template_ids=[],
    )
    record = submit_job(body, config=cfg, store=store)
    assert record["template_filter"] is None
    view = store.get_report(record["report_ids"][0])
    assert view is not None
    assert view.template_id == EXAMPLE_TEMPLATE_ID


def test_empty_jurisdiction_treated_as_no_filter(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    store = JobStore()
    body = JobSubmission(
        input_dir=str(_inputs(tmp_path).resolve()),
        jurisdiction="",
    )
    record = submit_job(body, config=cfg, store=store)
    assert record["template_filter"] is None


def test_jurisdiction_and_template_ids_combine_as_AND(tmp_path: Path) -> None:
    """Both filters present → template must satisfy both. Naming a real
    id but the wrong jurisdiction must yield zero matches."""
    cfg = _config(tmp_path)
    store = JobStore()
    body = JobSubmission(
        input_dir=str(_inputs(tmp_path).resolve()),
        jurisdiction="not_a_real_state",
        template_ids=[EXAMPLE_TEMPLATE_ID],
    )
    record = submit_job(body, config=cfg, store=store)
    audit = record["template_filter"]
    assert audit is not None
    assert audit["matched_template_ids"] == []
