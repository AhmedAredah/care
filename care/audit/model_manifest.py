"""Model manifest emitter (Phase 7).

Walks ``models/<provider>/...`` and SHA-256s every file, then pairs the
result with the static metadata declared by the provider class
(``provider_name``, ``provider_version``, network/license requirements,
hallucination risk, etc.). The resulting document is the canonical
input to:

- ``cli generate-sbom`` (embedded under the ``model_manifest`` key)
- ``scripts/compute_model_checksums.py`` (verifies provider integrity
  before enabling)
- ``scripts/package_offline_installer.sh`` (records what's bundled)

Provider detection is path-based: every immediate subdirectory of
``models/`` is treated as one provider entry. Top-level provider
groups (``ocr``, ``pii``, ``document_ai``) are recognised so the
output mirrors the registry layout.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..document_ai.registry import get_registry as get_vlm_registry
from ..ocr.registry import get_registry as get_ocr_registry
from ..pii.registry import get_registry as get_pii_registry

KNOWN_PROVIDER_GROUPS = ("ocr", "pii", "document_ai")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _walk_dir(root: Path) -> dict[str, str]:
    """Return ``{relative_path: sha256}`` for every file under ``root``."""
    if not root.exists() or not root.is_dir():
        return {}
    out: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        try:
            out[str(f.relative_to(root))] = _sha256_file(f)
        except OSError:  # pragma: no cover
            continue
    return out


def _provider_meta(group: str, name: str) -> dict[str, Any]:
    """Pull static metadata from the registered provider class."""
    try:
        if group == "ocr":
            cls = get_ocr_registry().get(name)
        elif group == "pii":
            cls = get_pii_registry().get(name)
        elif group == "document_ai":
            cls = get_vlm_registry().get(name)
        else:
            return {"registered": False}
    except Exception:  # noqa: BLE001
        return {"registered": False}

    return {
        "registered": True,
        "provider_name": getattr(cls, "name", name),
        "provider_version": getattr(cls, "version", "unknown"),
        "provider_type": getattr(cls, "provider_type", "unknown"),
        "requires_network": bool(getattr(cls, "requires_network", False)),
        "enabled_by_default": bool(getattr(cls, "enabled_by_default", False)),
        "generative_model": bool(getattr(cls, "generative_model", False)),
        "hallucination_risk": bool(getattr(cls, "hallucination_risk", False)),
    }


def build_model_manifest(*, models_dir: Path | None = None) -> dict[str, Any]:
    """Build the per-provider model manifest document.

    ``models_dir`` defaults to ``./models`` relative to CWD. Missing
    directory is OK — every group reports zero providers in that case.
    """
    root = Path(models_dir) if models_dir else Path("models")
    root = root.resolve()

    groups: dict[str, list[dict[str, Any]]] = {g: [] for g in KNOWN_PROVIDER_GROUPS}

    if root.exists():
        for group_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            group = group_dir.name
            if group not in groups:
                # Unknown group — still emit so packaging can audit it.
                groups[group] = []
            for provider_dir in sorted(p for p in group_dir.iterdir() if p.is_dir()):
                provider_name = provider_dir.name
                checksums = _walk_dir(provider_dir)
                meta = _provider_meta(group, provider_name)
                groups[group].append(
                    {
                        "provider_name": provider_name,
                        "model_path": str(provider_dir),
                        "model_path_present": bool(checksums),
                        "file_count": len(checksums),
                        "model_checksums": checksums,
                        "license": "see-provider-readme",
                        "metadata": meta,
                    }
                )

    return {
        "format": "care.model_manifest.v1",
        "models_dir": str(root),
        "generated_at": datetime.now(UTC).isoformat(),
        "groups": groups,
    }
