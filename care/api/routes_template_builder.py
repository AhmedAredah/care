"""Template-builder routes (Phase 8).

Five endpoints, all loopback-only and sandboxed:

    POST   /api/template-builder/source                  → create session
    GET    /api/template-builder/source/{token}          → session metadata
    GET    /api/template-builder/source/{token}/page/{n} → rendered PNG
    POST   /api/template-builder/preview                 → score in-progress template
    POST   /api/template-builder/save                    → validate + write YAML
    DELETE /api/template-builder/source/{token}          → cleanup

Every file access goes through ``safe_join``. Tokens are
regex-validated before any path operation. Saved templates are
validated through ``TemplateSchema.model_validate`` before any bytes
hit disk; existing files are never silently overwritten.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError

from ..core.config import AppConfig
from ..core.errors import (
    ConfigError,
    OfflineGuardError,
    PathTraversalError,
)
from ..core.paths import normalize_input_path
from ..core.security import safe_join
from ..document_ai.base import DocumentAIProvider
from ..document_ai.registry import get_registry as get_document_ai_registry
from ..extraction.diagram_extractor import extract_diagram
from ..extraction.narrative_extractor import extract_narrative
from ..services.region_suggester import (
    suggest_regions_for_page,
)
from ..services.template_builder import (
    TOKEN_RE,
    BuilderSessionError,
    TemplateBuilderStore,
    get_builder_store,
    session_to_dict,
)
from ..templates.detector import detect_template
from ..templates.registry import TemplateRegistry
from ..templates.schemas import TemplateSchema
from .deps import get_app_config

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/template-builder")

ID_SAFE_RE = re.compile(r"^[a-z0-9_]{1,64}$")


# ----- DI helpers --------------------------------------------------------


def _store(config: AppConfig = Depends(get_app_config)) -> TemplateBuilderStore:
    work_dir = Path(config.paths.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    return get_builder_store(work_dir=work_dir)


def _validate_token(token: str) -> None:
    if not TOKEN_RE.fullmatch(token):
        raise HTTPException(status_code=400, detail="invalid token")


def _validate_id_field(name: str, value: str) -> None:
    if not isinstance(value, str) or not ID_SAFE_RE.fullmatch(value):
        raise HTTPException(
            status_code=400,
            detail=f"{name} must match {ID_SAFE_RE.pattern}",
        )


# ----- request bodies ----------------------------------------------------


class SourceRequest(BaseModel):
    path: str = Field(..., description="Absolute path to a local PDF or image")
    dpi: int = 200


class PreviewRequest(BaseModel):
    token: str
    template: dict[str, Any]


class SaveRequest(BaseModel):
    token: str | None = None  # optional — useful for round-trip but not required
    jurisdiction: str
    template_id: str
    template: dict[str, Any]
    force: bool = False


class SuggestRegionsRequest(BaseModel):
    token: str
    page_index: int | None = None  # default: every page


# ----- POST /source ------------------------------------------------------


@router.post("/source", status_code=201)
def create_source(
    body: SourceRequest,
    store: TemplateBuilderStore = Depends(_store),
) -> dict[str, Any]:
    try:
        src = normalize_input_path(body.path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not src.exists() or not src.is_file():
        raise HTTPException(status_code=404, detail="source file not found")
    if body.dpi < 72 or body.dpi > 600:
        raise HTTPException(status_code=400, detail="dpi must be in [72, 600]")
    try:
        session = store.create_session(src, dpi=body.dpi)
    except BuilderSessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        _log.exception("create_session failed")
        raise HTTPException(
            status_code=500, detail=f"could not create session: {type(exc).__name__}"
        ) from exc
    return session_to_dict(session)


# ----- GET /source/{token} ----------------------------------------------


@router.get("/source/{token}")
def get_source(
    token: str,
    store: TemplateBuilderStore = Depends(_store),
) -> dict[str, Any]:
    _validate_token(token)
    session = store.get_session(token)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session_to_dict(session)


# ----- GET /source/{token}/page/{n} -------------------------------------


@router.get("/source/{token}/page/{page_index}")
def get_source_page(
    token: str,
    page_index: int,
    store: TemplateBuilderStore = Depends(_store),
) -> FileResponse:
    _validate_token(token)
    session = store.get_session(token)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if page_index < 0 or page_index >= len(session.pages):
        raise HTTPException(status_code=404, detail="page out of range")
    try:
        target = store.page_image_path(token, page_index)
    except BuilderSessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="page image not on disk")
    return FileResponse(
        path=str(target),
        media_type="image/png",
        filename=f"page_{page_index}.png",
    )


# ----- DELETE /source/{token} -------------------------------------------


@router.delete("/source/{token}")
def delete_source(
    token: str,
    store: TemplateBuilderStore = Depends(_store),
) -> dict[str, Any]:
    _validate_token(token)
    deleted = store.delete_session(token)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return {"token": token, "deleted": True}


# ----- helpers for preview / save ---------------------------------------


def _validate_template_dict(template_dict: dict[str, Any]) -> TemplateSchema:
    try:
        return TemplateSchema.model_validate(template_dict)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc


# ----- POST /preview ----------------------------------------------------


@router.post("/preview")
def preview(
    body: PreviewRequest,
    store: TemplateBuilderStore = Depends(_store),
    config: AppConfig = Depends(get_app_config),
) -> dict[str, Any]:
    _validate_token(body.token)
    session = store.get_session(body.token)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    template = _validate_template_dict(body.template)

    registry = TemplateRegistry([template])
    template_match = detect_template(
        session.document_ir,
        registry,
        confidence_threshold=config.template_detection.confidence_threshold,
    )

    source_image_paths: dict[int, Path] = {p.index: p.image_path for p in session.pages}
    diagram = extract_diagram(
        template,
        session.document_ir,
        work_dir=session.render_dir,
        source_image_paths=source_image_paths,
    )
    narrative = extract_narrative(template, session.document_ir)

    return {
        "template_match": {
            "template_id": template_match.template_id,
            "version": template_match.version,
            "confidence": template_match.confidence,
            "warnings": list(template_match.warnings),
            "evidence": {
                "anchor_text_found": list(template_match.evidence.anchor_text_found),
                "anchor_text_missing": list(template_match.evidence.anchor_text_missing),
                "form_number_match": template_match.evidence.form_number_match,
                "page_count_in_range": template_match.evidence.page_count_in_range,
                "candidate_scores": dict(template_match.evidence.candidate_scores),
            },
        },
        "diagram": (
            None
            if diagram is None
            else {
                "page_index": diagram.page_index,
                "bbox_norm": list(diagram.bbox_norm),
                "confidence": diagram.confidence,
                "requires_review": diagram.requires_review,
                "warnings": list(diagram.warnings),
            }
        ),
        "narrative": (
            None
            if narrative is None
            else {
                "page_index": narrative.page_index,
                "text_excerpt": (narrative.text or "")[:280],
                "anchor_start_found": narrative.anchor_start_found,
                "anchor_end_found": narrative.anchor_end_found,
                "confidence": narrative.confidence,
                "requires_review": narrative.requires_review,
                "warnings": list(narrative.warnings),
                "spans_pages": list(narrative.spans_pages),
            }
        ),
    }


# ----- POST /save -------------------------------------------------------


@router.post("/save")
def save_template(
    body: SaveRequest,
    config: AppConfig = Depends(get_app_config),
) -> dict[str, Any]:
    _validate_id_field("jurisdiction", body.jurisdiction)
    _validate_id_field("template_id", body.template_id)

    # Schema-validate the payload BEFORE touching the filesystem.
    template = _validate_template_dict(body.template)

    # The schema allows arbitrary template_id internally; but we tie
    # the on-disk filename to the user-supplied id field for clarity.
    if template.template_id != body.template_id:
        raise HTTPException(
            status_code=422,
            detail="template.template_id must equal request.template_id",
        )

    templates_root = Path(config.paths.templates_dir).resolve()
    templates_root.mkdir(parents=True, exist_ok=True)
    try:
        target = safe_join(
            templates_root,
            body.jurisdiction,
            f"{body.template_id}.yaml",
        )
    except PathTraversalError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if target.exists() and not body.force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"template already exists at {target}; "
                f"set force=true to overwrite"
            ),
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = template.model_dump(mode="json", exclude_none=True)
    target.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    return {
        "path": str(target),
        "jurisdiction": body.jurisdiction,
        "template_id": body.template_id,
        "validated": True,
        "overwritten": bool(body.force and target.exists()),
    }


# ----- POST /suggest-regions --------------------------------------------


def _maybe_load_layoutlm(config: AppConfig) -> DocumentAIProvider | None:
    """Load the LayoutLM provider iff explicitly enabled in config.

    Returns ``None`` when:

    - ``document_ai.enabled`` is False (default), OR
    - ``layoutlm`` is not in ``provider_chain``, OR
    - the per-provider config has ``enabled: false``, OR
    - load() raises (missing model files, transformers not installed) —
      we fall back to the heuristic so the UI still works.

    Loading inside the request handler is intentional: the suggester
    is opt-in feature; we don't want a permanent process-level
    Transformers import for a workflow most jobs never invoke.
    """
    if not config.document_ai.enabled:
        return None
    if "layoutlm" not in config.document_ai.provider_chain:
        return None
    provider_cfg = config.document_ai.providers.get("layoutlm", {})
    if provider_cfg.get("enabled") is False:
        return None
    try:
        cls = get_document_ai_registry().get("layoutlm")
        provider = cls()
        provider.load(provider_cfg)
        return provider
    except (ConfigError, OfflineGuardError) as exc:
        _log.info(
            "LayoutLM not available for suggestions (%s); using heuristic.",
            type(exc).__name__,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        _log.warning("LayoutLM load failed unexpectedly: %s; using heuristic.", exc)
        return None


@router.post("/suggest-regions")
def suggest_regions(
    body: SuggestRegionsRequest,
    store: TemplateBuilderStore = Depends(_store),
    config: AppConfig = Depends(get_app_config),
) -> dict[str, Any]:
    """Return region candidates for the operator to accept/reject.

    Suggestions are advisory: this endpoint never modifies the
    session, never writes a template, and never sets state on the
    server. The frontend renders the suggestions and the operator
    converts an accepted one into a regular template region via the
    existing draw-and-save pathway.
    """
    _validate_token(body.token)
    session = store.get_session(body.token)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    if body.page_index is not None:
        if body.page_index < 0 or body.page_index >= len(session.pages):
            raise HTTPException(status_code=404, detail="page out of range")
        target_pages = [session.pages[body.page_index]]
    else:
        target_pages = list(session.pages)

    layoutlm = _maybe_load_layoutlm(config)
    aggregated_flags: list[str] = []
    suggestions: list[dict[str, Any]] = []
    for page in target_pages:
        page_suggestions, page_flags = suggest_regions_for_page(
            page, layoutlm_provider=layoutlm
        )
        for s in page_suggestions:
            suggestions.append(s.to_dict())
        for flag in page_flags:
            if flag not in aggregated_flags:
                aggregated_flags.append(flag)

    if layoutlm is not None:
        try:
            layoutlm.close()
        except Exception:  # noqa: BLE001 — close failures are not actionable here
            pass

    backend = "layoutlm" if any(s["source"] == "layoutlm" for s in suggestions) else "heuristic"
    return {
        "token": body.token,
        "backend": backend,
        "requires_review": True,
        "qa_flags": aggregated_flags,
        "suggestions": suggestions,
        "notice": (
            "Suggestions are advisory only. They never enter a saved "
            "template or affect export until you click Accept. LayoutLM "
            "suggestions force human review on any pipeline run that "
            "uses them."
        ),
    }
