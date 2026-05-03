"""Pipeline runner used by the API and CLI (Phase 6).

Synchronously runs ``run_pipeline`` against an input directory, projects
each ``ReportArtifact`` to a sanitized ``ReportView``, and registers
both the job and reports in the JobStore. Errors mark the job as failed
and never propagate raw exceptions to API callers.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..core.config import AppConfig
from ..services.jobs import JobRecord, JobStore, report_view_from_artifact
from ..templates.registry import TemplateRegistry
from ..workers.pipeline import run_pipeline

_log = logging.getLogger(__name__)


def run_job_in_store(
    *,
    store: JobStore,
    job: JobRecord,
    input_dir: Path,
    config: AppConfig,
    template_registry: TemplateRegistry | None = None,
) -> JobRecord:
    """Run the pipeline and update the job record + report registry.

    ``template_registry`` lets the API/CLI pass a pre-filtered subset
    (per-job allowlist by jurisdiction or template_ids). When ``None``
    the pipeline loads every template from ``cfg.paths.templates_dir``.
    """
    store.mark_job_running(job.job_id)
    try:
        result = run_pipeline(
            input_dir, config=config, template_registry=template_registry
        )
    except Exception as exc:  # noqa: BLE001
        _log.exception("pipeline failed for job %s", job.job_id)
        store.mark_job_failed(job.job_id, error=type(exc).__name__)
        return store.get_job(job.job_id) or job

    report_ids: list[str] = []
    for artifact in result.artifacts:
        view = report_view_from_artifact(artifact)
        store.add_report(view)
        report_ids.append(view.report_id)
    store.mark_job_complete(job.job_id, report_ids=report_ids)
    return store.get_job(job.job_id) or job
