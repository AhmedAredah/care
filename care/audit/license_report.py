"""Flat license report (Phase 7).

Squashes the dependency list down to ``{package: license}`` plus a
counts-by-license summary. Every consumer of the SBOM sees the same
license view regardless of how packaging tooling formats the full
dependency block.
"""
from __future__ import annotations

from collections import Counter
from typing import Any


def _normalize(license_field: str) -> str:
    if not license_field:
        return "UNKNOWN"
    text = str(license_field).strip()
    if not text:
        return "UNKNOWN"
    # Many wheels embed full license texts in the License field. Compact
    # those down to the first non-empty line to avoid SBOM bloat.
    first_line = text.splitlines()[0].strip()
    return first_line or "UNKNOWN"


def build_license_report(distributions: list[dict[str, Any]]) -> dict[str, Any]:
    by_package: dict[str, str] = {}
    counter: Counter[str] = Counter()
    for dist in distributions:
        name = dist.get("name") or "UNKNOWN"
        license_value = _normalize(dist.get("license") or "")
        by_package[name] = license_value
        counter[license_value] += 1
    return {
        "format": "care.license_report.v1",
        "package_count": len(by_package),
        "by_package": dict(sorted(by_package.items())),
        "counts_by_license": dict(sorted(counter.items())),
    }
