"""Configuration endpoints (Phase 13.1 + 13.2 + 13.3 + 13.6 + 13.7).

The GUI uses these to render an honest view of what the running app
believes its configuration is, dry-run proposed edits, commit them
back to ``config.yaml`` with comments and ordering preserved, manage
cloud-LLM secrets stored in a sidecar ``secrets.yaml``, and signal
when an on-disk change requires a server restart to take effect.

- ``GET /api/config`` — current effective config as JSON, with every
  API-key-shaped field replaced by ``***REDACTED***`` via
  :func:`care.llm.safety.redact_secrets`. Path strings (model
  dirs, work_dir, etc.) are kept verbatim because the GUI needs them
  to render "where on disk is this configured?" — they are not
  secrets, just operator-supplied filesystem locations.

- ``GET /api/config/schema`` — Pydantic JSON schema for ``AppConfig``,
  so the frontend can render section-aware forms generically (Phase
  13.5) instead of hardcoding every field.

- ``GET /api/config/source`` — small audit payload telling the
  operator which path on disk the running config was loaded from.
  Helps diagnose "why isn't my edit taking effect?" when the user
  has both ``./config.yaml`` and ``./backend/config.yaml``.

- ``GET /api/config/locked-keys`` (13.2) — the locked
  rules. The frontend uses this to grey out fields the operator
  cannot touch and to render the reason inline.

- ``POST /api/config/validate`` (13.2) — dry-run validation. The
  body is a partial config dict that gets deep-merged onto the
  current config; the result is run through Pydantic validation
  and the locked check. Returns ``ok=true`` only when
  both pass.

- ``PATCH /api/config`` (13.3) — apply the validated patch to
  ``config.yaml`` on disk. Comments and ordering survive the round
  trip (ruamel.yaml). A timestamped backup is created before each
  write; we keep the most recent ``MAX_BACKUPS`` and prune the rest.
  Two simultaneous PATCHes serialise on a process-level lock; readers
  see only complete files because the write is ``tmp + os.replace``.

- ``GET /api/config/secrets`` (13.6) — list the **names** of stored
  secrets. Values are NEVER echoed.

- ``POST /api/config/secrets`` (13.6) — write-only. Body
  ``{"name": "FOO_API_KEY", "value": "..."}``. Saves to the sidecar
  with ``chmod 600`` and returns the name only.

- ``DELETE /api/config/secrets/{name}`` (13.6) — remove a stored
  secret.

- ``GET /api/config/secrets/derive-name`` (13.6) — given a dotted
  config path (``?path=llm.providers.openai.api_key``), return the
  conventional secret name (``OPENAI_API_KEY``) so the GUI can
  pre-fill the dialog without baking the convention into JS.

- ``GET /api/config/restart-required`` (13.7) — diff the boot
  snapshot (captured by ``cli serve`` just before uvicorn binds)
  against the current on-disk config. Returns the list of paths
  that always require a restart, plus the subset that has actually
  drifted ("pending changes"). The Settings page renders a banner
  when ``pending_restart=true``.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import ValidationError

from ..core.config import AppConfig, DEFAULT_CONFIG_PATHS
from ..core.config_writer import resolve_write_path, save_patch
from ..core.governance_guard import (
    check_immutable_violations,
    deep_merge,
    list_locked_keys,
)
from ..core.runtime_state import (
    RESTART_REQUIRED_PATHS,
    get_boot_snapshot,
)
from ..core.secrets import (
    delete_secret,
    derive_name_for_path,
    is_valid_secret_name,
    list_secret_names,
    resolve_secrets_path,
    save_secret,
)
from ..llm.safety import redact_secrets
from .deps import get_app_config

router = APIRouter()

_log = logging.getLogger(__name__)


def _validate_patch(
    patch: dict[str, Any], current: AppConfig
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Shared logic between validate and PATCH.

    Returns the merged config, the structured Pydantic errors, and
    the list of locked violations.
    """
    base = current.model_dump(mode="json")
    merged = deep_merge(base, patch)

    pydantic_errors: list[dict[str, Any]] = []
    try:
        AppConfig.model_validate(merged)
    except ValidationError as exc:
        pydantic_errors = [
            {
                "loc": [str(p) for p in err.get("loc", ())],
                "msg": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]

    governance_errors = check_immutable_violations(merged)
    return merged, pydantic_errors, governance_errors


@router.get("/config")
def get_config(config: AppConfig = Depends(get_app_config)) -> dict[str, Any]:
    """Return the effective config as a redacted JSON document."""
    raw = config.model_dump(mode="json")
    return redact_secrets(raw)


@router.get("/config/schema")
def get_config_schema() -> dict[str, Any]:
    """Return the JSON schema for AppConfig.

    Stable across requests (it's derived from the Pydantic model
    definition), so the frontend can cache this aggressively.
    """
    return AppConfig.model_json_schema()


@router.get("/config/source")
def get_config_source() -> dict[str, Any]:
    """Return where the running config was loaded from.

    The frontend shows this so the operator knows which file the
    Settings UI will write to in Phase 13.3, and can spot the case
    where the app silently fell back to defaults (no file found).
    """
    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            resolved = Path(candidate).resolve()
            return {
                "path": str(resolved),
                "exists": True,
                "is_default": False,
            }
    return {
        "path": None,
        "exists": False,
        "is_default": True,
    }


@router.get("/config/locked-keys")
def get_locked_keys() -> dict[str, Any]:
    """Return locked rules for the GUI.

    Each rule has a dotted ``path`` (e.g. ``logging.log_raw_pii``), a
    ``forbidden_value`` the operator can never set, and a ``reason``
    citing the locked rule. The frontend greys out fields whose
    path matches a locked rule.
    """
    return {"locked_keys": list_locked_keys()}


@router.post("/config/validate")
def validate_config(
    body: dict[str, Any] = Body(...),
    current: AppConfig = Depends(get_app_config),
) -> dict[str, Any]:
    """Dry-run validation of a proposed config patch.

    Body is a partial config dict that gets deep-merged onto the
    current config. The merged result is then:

    1. Run through ``AppConfig.model_validate`` so type errors are
       caught early.
    2. Checked against the locked rules in
       :mod:`care.core.governance_guard`.

    The PATCH endpoint runs this same logic before writing to disk;
    this endpoint exposes it so the frontend can show errors *before*
    the user clicks "Save".
    """
    _, pydantic_errors, governance_errors = _validate_patch(body, current)
    return {
        "ok": not pydantic_errors and not governance_errors,
        "pydantic_errors": pydantic_errors,
        "governance_errors": governance_errors,
    }


@router.patch("/config")
def patch_config(
    body: dict[str, Any] = Body(...),
    current: AppConfig = Depends(get_app_config),
) -> dict[str, Any]:
    """Apply a partial config patch to ``config.yaml`` on disk.

    Validation is performed first (same code path as
    ``POST /config/validate``). On any error the request is rejected
    with HTTP 400 and nothing is written. On success the patch is
    merged into the current YAML preserving comments and ordering,
    a timestamped ``.bak`` is created next to the file, and the
    response includes the new redacted config plus the backup path
    so the caller can roll back from the GUI.

    An empty patch (``{}``) is a no-op: it returns 200 with the
    current state and writes a "touch" save (still creates a backup
    so the audit trail is uniform). Operators can use this as a
    cheap "save current state as a checkpoint" gesture.
    """
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail="request body must be a JSON object",
        )

    _, pydantic_errors, governance_errors = _validate_patch(body, current)
    if pydantic_errors or governance_errors:
        raise HTTPException(
            status_code=400,
            detail={
                "pydantic_errors": pydantic_errors,
                "governance_errors": governance_errors,
            },
        )

    try:
        audit = save_patch(body)
    except (OSError, ValueError) as exc:
        _log.exception("config save failed")
        raise HTTPException(
            status_code=500,
            detail=f"failed to save config: {type(exc).__name__}: {exc}",
        ) from exc

    # Re-load from disk so the response reflects exactly what the
    # next pipeline run will see (and proves the round-trip worked).
    from ..core.config import load_config  # local import to dodge cycle

    new_cfg = load_config(audit["target_path"])
    return {
        "ok": True,
        "target_path": audit["target_path"],
        "backup_path": audit["backup_path"],
        "config": redact_secrets(new_cfg.model_dump(mode="json")),
    }


# ----- Phase 13.6 — secrets sidecar -----------------------------------


def _secrets_path() -> Path:
    """The on-disk sidecar. Lives next to whichever config.yaml is
    canonical for this deployment."""
    return resolve_secrets_path(resolve_write_path())


@router.get("/config/secrets")
def get_secrets_list() -> dict[str, Any]:
    """List the names of stored secrets (values are never returned)."""
    path = _secrets_path()
    return {
        "secrets_path": str(path),
        "names": list_secret_names(path),
    }


@router.post("/config/secrets", status_code=201)
def post_secret(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Write a single secret. Body: ``{"name": "...", "value": "..."}``.

    The endpoint is **write-only**: the response confirms the name
    but never echoes the value. A 400 is returned for malformed
    names (the placeholder regex is strict).
    """
    name = body.get("name")
    value = body.get("value")
    if not isinstance(name, str) or not name:
        raise HTTPException(status_code=400, detail="missing 'name'")
    if not is_valid_secret_name(name):
        raise HTTPException(
            status_code=400,
            detail="name must match ^[A-Z][A-Z0-9_]*$ (SCREAMING_SNAKE_CASE)",
        )
    if not isinstance(value, str) or value == "":
        raise HTTPException(status_code=400, detail="missing or empty 'value'")
    path = _secrets_path()
    try:
        save_secret(path, name, value)
    except (OSError, ValueError) as exc:
        _log.exception("secret save failed")
        raise HTTPException(
            status_code=500,
            detail=f"failed to save secret: {type(exc).__name__}: {exc}",
        ) from exc
    return {
        "ok": True,
        "name": name,
        "secrets_path": str(path),
        "placeholder": "${secret:" + name + "}",
    }


@router.delete("/config/secrets/{name}", status_code=204)
def delete_secret_by_name(name: str) -> None:
    if not is_valid_secret_name(name):
        raise HTTPException(
            status_code=400,
            detail="name must match ^[A-Z][A-Z0-9_]*$",
        )
    path = _secrets_path()
    if not delete_secret(path, name):
        raise HTTPException(status_code=404, detail="secret not found")


@router.get("/config/secrets/derive-name")
def derive_secret_name(
    path: str = Query(..., description="dotted config path"),
) -> dict[str, Any]:
    """Return the conventional secret name for a config field."""
    name = derive_name_for_path(path)
    return {
        "config_path": path,
        "secret_name": name,
        "placeholder": ("${secret:" + name + "}") if name else None,
    }


# ----- Phase 13.7 — restart-required signal ----------------------------


def _value_at_path(data: dict[str, Any], dotted: str) -> Any:
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


@router.get("/config/restart-required")
def get_restart_required(
    config: AppConfig = Depends(get_app_config),
) -> dict[str, Any]:
    """Tell the GUI whether the live binding lags the on-disk config.

    Three states:

    - ``pending_restart=true`` — the on-disk config differs from the
      boot snapshot on at least one always-restart-required path.
      The Settings page shows a yellow banner.
    - ``pending_restart=false`` — boot snapshot matches the disk;
      no restart is needed.
    - ``pending_restart=null`` — the boot snapshot is empty (the
      server was launched outside ``cli serve``, e.g. by ``pytest``
      or a hand-rolled uvicorn invocation). Displays "unknown".

    The endpoint never restarts anything itself — auto-restart is
    deferred per the "ask before risky actions" principle.
    Operators stop and re-launch the server in their terminal.
    """
    snapshot = get_boot_snapshot()
    current_dump = config.model_dump(mode="json")
    pending: list[dict[str, Any]] = []
    if snapshot is not None:
        for path in RESTART_REQUIRED_PATHS:
            current_value = _value_at_path(current_dump, path)
            boot_value = snapshot.get(path)
            if current_value != boot_value:
                pending.append({
                    "path": path,
                    "boot_value": boot_value,
                    "current_value": current_value,
                })
    return {
        "requires_restart_paths": list(RESTART_REQUIRED_PATHS),
        "boot_snapshot": snapshot,
        "pending_restart": (None if snapshot is None else bool(pending)),
        "pending_changes": pending,
    }
