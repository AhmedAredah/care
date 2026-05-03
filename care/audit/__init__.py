"""Audit emitters (Phase 7).

- ``sbom`` — dependency / package SBOM (placeholder format until a
  real CycloneDX/SPDX emitter lands in production).
- ``model_manifest`` — per-provider model manifest with checksums.
- ``license_report`` — flat license report derived from package metadata.
"""
from __future__ import annotations

from .license_report import build_license_report
from .model_manifest import build_model_manifest
from .sbom import build_sbom

__all__ = [
    "build_sbom",
    "build_model_manifest",
    "build_license_report",
]
