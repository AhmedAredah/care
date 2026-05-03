"""Process-local services used by the API and CLI."""
from __future__ import annotations

from .jobs import (
    JobRecord,
    JobStatus,
    JobStore,
    ReportView,
    ReviewState,
    get_job_store,
    reset_job_store,
)
from .template_builder import (
    BuilderPage,
    BuilderSession,
    BuilderSessionError,
    BuilderWord,
    TemplateBuilderStore,
    get_builder_store,
    pixel_bbox_to_norm,
    reset_builder_store,
    session_to_dict,
)

__all__ = [
    "JobRecord",
    "JobStatus",
    "JobStore",
    "ReportView",
    "ReviewState",
    "get_job_store",
    "reset_job_store",
    "BuilderPage",
    "BuilderSession",
    "BuilderSessionError",
    "BuilderWord",
    "TemplateBuilderStore",
    "get_builder_store",
    "pixel_bbox_to_norm",
    "reset_builder_store",
    "session_to_dict",
]
