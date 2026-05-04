"""Process-local job + report store (Phase 6).

The API and CLI share a single in-memory ``JobStore`` so a job submitted
through one entrypoint is visible from the other within the same
process. The store never persists anything outside of the configured
``work_dir`` and ``export_dir``; restarts drop in-memory state.

Reports are addressed by ``report_id == file_entry.sha256[:16]`` so that
URLs never leak the original filename or any user input. Path-based
file access from API routes always re-derives paths from this id and
the configured export/work directories — never trusts a client-supplied
path.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..core.config import AppConfig

JobStatus = str  # "pending" | "running" | "complete" | "failed"


@dataclass
class ReviewState:
    decision: str = "PENDING"  # "PENDING" | "APPROVED" | "REJECTED"
    reviewer: str | None = None
    notes: str | None = None
    reviewed_at: str | None = None


@dataclass
class ReportView:
    """Subset of ReportArtifact safe to expose through the API.

    Carries no DocumentIR words, no raw OCR/VLM dumps, no source paths
    that could disclose user filesystem layout. Anything the API hands
    out for a report flows through this view.
    """

    report_id: str  # short sha (first 16 chars)
    source_sha256: str
    source_file_name: str
    file_type: str
    template_id: str
    template_version: str | None
    template_confidence: float
    text_source: str
    ocr_provider_used: str | None
    qa_decision: str
    qa_export_blocked: bool
    qa_flags: list[str]
    qa_blocking_reasons: list[str]
    qa_requires_human_review: bool
    qa_pii_entity_count: int
    qa_pii_unmapped_count: int
    diagram_confidence: float | None
    narrative_confidence: float | None
    export_dir: str | None
    review: ReviewState = field(default_factory=ReviewState)
    vlm_warning_codes: list[str] = field(default_factory=list)


@dataclass
class JobRecord:
    job_id: str
    status: JobStatus
    submitted_at: str
    started_at: str | None = None
    finished_at: str | None = None
    input_dir: str | None = None
    error: str | None = None
    report_ids: list[str] = field(default_factory=list)
    template_filter: dict[str, Any] | None = None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    """Thread-safe in-memory job + report registry."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, JobRecord] = {}
        self._reports: dict[str, ReportView] = {}
        self._config = config

    # ----- jobs -----------------------------------------------------------

    def create_job(
        self,
        *,
        input_dir: str | None = None,
        template_filter: dict[str, Any] | None = None,
    ) -> JobRecord:
        with self._lock:
            job_id = uuid.uuid4().hex[:16]
            record = JobRecord(
                job_id=job_id,
                status="pending",
                submitted_at=_now_iso(),
                input_dir=input_dir,
                template_filter=template_filter,
            )
            self._jobs[job_id] = record
            return record

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[JobRecord]:
        with self._lock:
            return list(self._jobs.values())

    def mark_job_running(self, job_id: str) -> None:
        with self._lock:
            j = self._jobs[job_id]
            j.status = "running"
            j.started_at = _now_iso()

    def mark_job_complete(self, job_id: str, *, report_ids: list[str]) -> None:
        with self._lock:
            j = self._jobs[job_id]
            j.status = "complete"
            j.finished_at = _now_iso()
            j.report_ids = list(report_ids)

    def mark_job_failed(self, job_id: str, *, error: str) -> None:
        with self._lock:
            j = self._jobs[job_id]
            j.status = "failed"
            j.finished_at = _now_iso()
            j.error = error

    # ----- reports --------------------------------------------------------

    def add_report(self, view: ReportView) -> None:
        with self._lock:
            self._reports[view.report_id] = view

    def get_report(self, report_id: str) -> ReportView | None:
        with self._lock:
            return self._reports.get(report_id)

    def list_reports(self) -> list[ReportView]:
        with self._lock:
            return list(self._reports.values())

    # ----- review ---------------------------------------------------------

    def set_review(
        self,
        report_id: str,
        *,
        decision: str,
        reviewer: str | None = None,
        notes: str | None = None,
    ) -> ReportView | None:
        if decision not in {"APPROVED", "REJECTED"}:
            raise ValueError(
                f"review decision must be APPROVED or REJECTED, got {decision!r}"
            )
        with self._lock:
            view = self._reports.get(report_id)
            if view is None:
                return None
            view.review = ReviewState(
                decision=decision,
                reviewer=reviewer,
                notes=notes,
                reviewed_at=_now_iso(),
            )
            return view


# ----- module-level singleton -------------------------------------------

_store: JobStore | None = None
_store_lock = threading.Lock()


def get_job_store() -> JobStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = JobStore()
        return _store


def reset_job_store() -> None:
    """Used by tests to start with a clean registry."""
    global _store
    with _store_lock:
        _store = None


# ----- ReportArtifact → ReportView projection ---------------------------


def report_view_from_artifact(artifact: Any) -> ReportView:
    """Build a sanitized ReportView from a pipeline ReportArtifact.

    Strips anything that could leak originals or raw provider output:
    - no DocumentIR
    - no OCR/VLM tokens
    - no source filesystem paths beyond export_dir
    """
    qa = artifact.qa
    short = artifact.file_entry.sha256[:16]
    export_path: str | None = None
    if artifact.export_result is not None and not artifact.export_result.skipped:
        export_path = artifact.export_result.output_dir
    vlm_codes = sorted({w.code for w in (artifact.vlm_warnings or [])})
    return ReportView(
        report_id=short,
        source_sha256=artifact.file_entry.sha256,
        source_file_name=artifact.file_entry.name,
        file_type=artifact.file_entry.file_type,
        template_id=artifact.template_match.template_id,
        template_version=artifact.template_match.version,
        template_confidence=float(artifact.template_match.confidence),
        text_source=artifact.text_source,
        ocr_provider_used=artifact.ocr_provider_used,
        qa_decision=qa.export_decision,
        qa_export_blocked=qa.export_blocked,
        qa_flags=list(qa.qa_flags),
        qa_blocking_reasons=list(qa.blocking_reasons),
        qa_requires_human_review=qa.requires_human_review,
        qa_pii_entity_count=int(qa.pii_entity_count),
        qa_pii_unmapped_count=int(qa.pii_unmapped_count),
        diagram_confidence=qa.diagram_confidence,
        narrative_confidence=qa.narrative_confidence,
        export_dir=export_path,
        vlm_warning_codes=vlm_codes,
    )


def review_state_to_dict(state: ReviewState) -> dict[str, Any]:
    return asdict(state)


def report_view_to_dict(view: ReportView) -> dict[str, Any]:
    return asdict(view)


def job_record_to_dict(record: JobRecord) -> dict[str, Any]:
    return asdict(record)
