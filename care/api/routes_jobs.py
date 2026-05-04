"""Job submission and status (Phase 6).

POST /jobs accepts an absolute path to a directory of crash report
files. The path is validated to exist; the pipeline runs synchronously
(small/medium volumes only — Phase 7 packaging may swap in a worker
queue). Original input files are NEVER returned through any endpoint
on this router.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.config import AppConfig
from ..core.paths import normalize_input_path
from ..services.jobs import JobStore, job_record_to_dict
from ..templates import load_templates_from_directory
from ..templates.registry import TemplateRegistry
from .deps import get_app_config, get_store
from .runner import run_job_in_store

router = APIRouter()


class JobSubmission(BaseModel):
    input_dir: str = Field(..., description="Absolute path to a directory of input files")
    jurisdiction: str | None = Field(
        default=None,
        description=(
            "Optional jurisdiction allowlist. When set, only templates whose "
            "jurisdiction field matches will be considered. Empty string or "
            "missing means no filter (use all templates)."
        ),
    )
    template_ids: list[str] | None = Field(
        default=None,
        description=(
            "Optional template_id allowlist. When set, only templates with "
            "an id in this list will be considered. Empty list or missing "
            "means no filter (use all templates). When combined with "
            "jurisdiction, both filters apply (AND)."
        ),
    )


def _build_filtered_registry(
    config: AppConfig, body: JobSubmission
) -> tuple[TemplateRegistry, dict[str, object] | None]:
    """Load every template from disk and apply the per-job allowlist.

    Returns the (possibly unfiltered) registry plus a small audit dict
    recording the effective filter — or None when no filter applied.
    """
    full = TemplateRegistry(load_templates_from_directory(config.paths.templates_dir))
    filtered = full.filter_by(
        jurisdiction=body.jurisdiction,
        template_ids=body.template_ids,
    )
    audit: dict[str, object] | None = None
    juris = (body.jurisdiction or "").strip() or None
    ids = [t for t in (body.template_ids or []) if t and t.strip()]
    if juris is not None or ids:
        audit = {
            "jurisdiction": juris,
            "template_ids": ids or None,
            "matched_template_ids": filtered.names(),
        }
    return filtered, audit


@router.post("/jobs", status_code=202)
def submit_job(
    body: JobSubmission,
    config: AppConfig = Depends(get_app_config),
    store: JobStore = Depends(get_store),
) -> dict[str, object]:
    try:
        input_dir = normalize_input_path(body.input_dir)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="input_dir must be an absolute path",
        ) from exc
    if not input_dir.exists() or not input_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail="input_dir does not exist or is not a directory",
        )
    registry, template_filter = _build_filtered_registry(config, body)
    job = store.create_job(
        input_dir=str(input_dir.resolve()),
        template_filter=template_filter,
    )
    record = run_job_in_store(
        store=store,
        job=job,
        input_dir=input_dir,
        config=config,
        template_registry=registry,
    )
    return job_record_to_dict(record)


@router.get("/jobs")
def list_jobs(store: JobStore = Depends(get_store)) -> dict[str, list[dict]]:
    return {"jobs": [job_record_to_dict(j) for j in store.list_jobs()]}


@router.get("/jobs/{job_id}")
def get_job(
    job_id: str,
    store: JobStore = Depends(get_store),
) -> dict[str, object]:
    record = store.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job_record_to_dict(record)
