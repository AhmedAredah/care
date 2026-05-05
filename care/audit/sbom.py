"""SBOM (Software Bill of Materials) emitter (Phase 7).

Returns a self-describing dict with three sections:

- ``dependencies``  — every Python distribution loadable in the
  current environment (name + version + license + project URL when
  available)
- ``model_manifest`` — per-provider model manifest (see
  :mod:`care.audit.model_manifest`)
- ``licenses``       — flat ``{package: license}`` report derived from
  the same dependency metadata (see
  :mod:`care.audit.license_report`)

The format is intentionally narrow and stable. Phase 7 keeps it as a
``care.sbom.v1`` document; future packaging work can
swap in CycloneDX or SPDX without touching call sites.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:  # pragma: no cover
    import importlib.metadata as md
except ImportError:  # pragma: no cover
    import importlib_metadata as md  # type: ignore[no-redef]

from ..core.constants import APP_NAME, APP_VERSION
from .license_report import build_license_report
from .model_manifest import build_model_manifest


def _iter_distributions() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for dist in md.distributions():
        meta = dist.metadata or {}
        name = meta.get("Name") if hasattr(meta, "get") else None
        if not name:
            continue
        # PEP 639 expression (License-Expression) takes precedence over
        # the legacy free-text License field. Distributions that adopt
        # SPDX expressions stop populating the legacy field, so falling
        # back is required for accurate reporting.
        license_expr = meta.get("License-Expression") if hasattr(meta, "get") else None
        license_legacy = meta.get("License") if hasattr(meta, "get") else None
        out.append(
            {
                "name": name,
                "version": dist.version or "unknown",
                "license": license_expr or license_legacy or "UNKNOWN",
                "homepage": (meta.get("Home-page") if hasattr(meta, "get") else None) or None,
                "summary": (meta.get("Summary") if hasattr(meta, "get") else None) or None,
            }
        )
    out.sort(key=lambda d: d["name"].lower())
    return out


def build_sbom(
    *,
    models_dir: Path | None = None,
    include_packages: bool = True,
) -> dict[str, Any]:
    """Build the in-memory SBOM document.

    ``models_dir`` is forwarded to :func:`build_model_manifest`. When
    omitted, the model manifest section reports zero models — useful
    for dependency-only SBOMs.

    ``include_packages=False`` produces a compact SBOM with the model
    manifest and license report only.
    """
    distributions = _iter_distributions() if include_packages else []
    license_report = build_license_report(distributions)
    model_manifest = build_model_manifest(models_dir=models_dir)

    return {
        "format": "care.sbom.v1",
        "app": {"name": APP_NAME, "version": APP_VERSION},
        "generated_at": datetime.now(UTC).isoformat(),
        "dependencies": distributions,
        "dependency_count": len(distributions),
        "licenses": license_report,
        "model_manifest": model_manifest,
        "notes": [
            "care is offline-first; this SBOM lists everything "
            "that COULD be loaded, not everything that WILL be loaded at runtime.",
            "Optional providers (Piiranha, Kosmos-2.5) remain DISABLED BY DEFAULT.",
            "Model files are not included in the SBOM payload itself; only their "
            "filenames and SHA-256 checksums.",
        ],
    }
