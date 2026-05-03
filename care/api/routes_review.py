"""Review state endpoints (Phase 6).

Reviewers may APPROVE or REJECT a report. These endpoints update the
in-memory review state ONLY — they never re-write redacted artifacts,
flip the QA gate, or unblock a report whose export was already blocked
by the fail-closed pipeline.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..services.jobs import JobStore, review_state_to_dict
from .deps import get_store
from .routes_reports import _require_report

router = APIRouter()


class ReviewBody(BaseModel):
    reviewer: Optional[str] = None
    notes: Optional[str] = None


@router.post("/reports/{report_id}/review/approve")
def approve_report(
    report_id: str,
    body: ReviewBody,
    store: JobStore = Depends(get_store),
) -> dict[str, object]:
    view = _require_report(report_id, store)
    if view.qa_export_blocked:
        raise HTTPException(
            status_code=409,
            detail=(
                "cannot approve — pipeline QA gate already blocked the export. "
                "Reprocess the report after correcting upstream input."
            ),
        )
    updated = store.set_review(
        report_id, decision="APPROVED", reviewer=body.reviewer, notes=body.notes
    )
    assert updated is not None
    return {
        "report_id": report_id,
        "review": review_state_to_dict(updated.review),
        "qa_export_blocked": updated.qa_export_blocked,
    }


@router.post("/reports/{report_id}/review/reject")
def reject_report(
    report_id: str,
    body: ReviewBody,
    store: JobStore = Depends(get_store),
) -> dict[str, object]:
    view = _require_report(report_id, store)
    updated = store.set_review(
        report_id, decision="REJECTED", reviewer=body.reviewer, notes=body.notes
    )
    assert updated is not None
    return {
        "report_id": report_id,
        "review": review_state_to_dict(updated.review),
        "qa_export_blocked": updated.qa_export_blocked,
    }
