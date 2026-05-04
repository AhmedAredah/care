"""Report inspection endpoints (Phase 6).

Every endpoint validates that the requested file lives under the
configured ``export_dir`` and re-derives paths from the immutable
``report_id`` (== ``source_sha256[:16]``) so URL inputs cannot direct
file reads outside that sandbox.

These endpoints intentionally do NOT expose:
- the original PDF or scan
- raw OCR / VLM dumps
- DocumentIR words
- unredacted narrative text
- raw PII text values

Only the redacted public artifacts and structured QA / manifest data
written by the Phase 4 exporter are returned.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from ..core.config import AppConfig
from ..core.errors import PathTraversalError
from ..core.security import safe_join
from ..services.jobs import JobStore, ReportView, report_view_to_dict
from .deps import get_app_config, get_store

router = APIRouter()

REPORT_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def _validate_report_id(report_id: str) -> None:
    if not REPORT_ID_RE.fullmatch(report_id):
        raise HTTPException(
            status_code=400, detail="invalid report_id"
        )


def _resolve_export_subpath(
    config: AppConfig, report: ReportView, *parts: str
) -> Path:
    """Re-derive a redacted artifact path inside the configured export_dir.

    Raises 404 if the file is missing. Raises 400 on traversal attempts.
    """
    export_root = Path(config.paths.export_dir).resolve()
    subdir = f"report_{report.source_sha256[:16]}"
    try:
        target = safe_join(export_root, subdir, *parts)
    except PathTraversalError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return target


def _require_report(report_id: str, store: JobStore) -> ReportView:
    _validate_report_id(report_id)
    view = store.get_report(report_id)
    if view is None:
        raise HTTPException(status_code=404, detail="report not found")
    return view


@router.get("/reports/{report_id}")
def get_report(
    report_id: str,
    store: JobStore = Depends(get_store),
) -> dict[str, object]:
    return report_view_to_dict(_require_report(report_id, store))


@router.get("/reports/{report_id}/qa")
def get_report_qa(
    report_id: str,
    store: JobStore = Depends(get_store),
    config: AppConfig = Depends(get_app_config),
) -> JSONResponse:
    view = _require_report(report_id, store)
    if view.qa_export_blocked:
        # No qa.json on disk for blocked reports — synthesize from the view.
        return JSONResponse(
            {
                "export_decision": view.qa_decision,
                "export_blocked": view.qa_export_blocked,
                "blocking_reasons": view.qa_blocking_reasons,
                "qa_flags": view.qa_flags,
                "requires_human_review": view.qa_requires_human_review,
                "template_confidence": view.template_confidence,
                "diagram_confidence": view.diagram_confidence,
                "narrative_confidence": view.narrative_confidence,
            }
        )
    target = _resolve_export_subpath(config, view, "qa.json")
    return JSONResponse(json.loads(target.read_text(encoding="utf-8")))


@router.get("/reports/{report_id}/manifest")
def get_report_manifest(
    report_id: str,
    store: JobStore = Depends(get_store),
    config: AppConfig = Depends(get_app_config),
) -> JSONResponse:
    view = _require_report(report_id, store)
    if view.qa_export_blocked:
        raise HTTPException(
            status_code=409,
            detail="manifest unavailable — export was blocked by QA gate",
        )
    target = _resolve_export_subpath(config, view, "manifest.json")
    return JSONResponse(json.loads(target.read_text(encoding="utf-8")))


@router.get("/reports/{report_id}/diagram")
def get_report_diagram(
    report_id: str,
    store: JobStore = Depends(get_store),
    config: AppConfig = Depends(get_app_config),
) -> FileResponse:
    view = _require_report(report_id, store)
    if view.qa_export_blocked:
        raise HTTPException(
            status_code=409,
            detail="diagram unavailable — export was blocked by QA gate",
        )
    target = _resolve_export_subpath(config, view, "diagram.redacted.png")
    return FileResponse(
        path=str(target),
        media_type="image/png",
        filename="diagram.redacted.png",
    )


@router.get("/reports/{report_id}/narrative")
def get_report_narrative(
    report_id: str,
    store: JobStore = Depends(get_store),
    config: AppConfig = Depends(get_app_config),
    format: str = "json",
):
    view = _require_report(report_id, store)
    if view.qa_export_blocked:
        raise HTTPException(
            status_code=409,
            detail="narrative unavailable — export was blocked by QA gate",
        )
    if format == "text":
        target = _resolve_export_subpath(config, view, "narrative.redacted.txt")
        return PlainTextResponse(target.read_text(encoding="utf-8"))
    if format != "json":
        raise HTTPException(
            status_code=400, detail="format must be 'json' or 'text'"
        )
    target = _resolve_export_subpath(config, view, "narrative.redacted.json")
    return JSONResponse(json.loads(target.read_text(encoding="utf-8")))
