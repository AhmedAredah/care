"""Export browser endpoint (Phase 6).

Lists every redacted-report directory currently under the configured
``export_dir``. NEVER lists files outside that directory or returns
file contents directly here — clients must use the per-report
endpoints for content access (which enforce QA gating + path safety).
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ..core.config import AppConfig
from .deps import get_app_config

router = APIRouter()

EXPECTED_FILES = {
    "diagram.redacted.png",
    "narrative.redacted.txt",
    "narrative.redacted.json",
    "manifest.json",
    "qa.json",
}

REPORT_DIR_RE = re.compile(r"^report_[0-9a-f]{16}$")


@router.get("/exports")
def list_exports(config: AppConfig = Depends(get_app_config)) -> dict[str, object]:
    export_root = Path(config.paths.export_dir).resolve()
    if not export_root.exists():
        return {"export_dir": str(export_root), "reports": []}

    out: list[dict] = []
    for entry in sorted(export_root.iterdir()):
        if not entry.is_dir() or not REPORT_DIR_RE.fullmatch(entry.name):
            continue
        files: list[str] = []
        for f in entry.iterdir():
            if not f.is_file():
                continue
            if f.name not in EXPECTED_FILES:
                continue
            files.append(f.name)
        out.append(
            {
                "report_id": entry.name.removeprefix("report_"),
                "files": sorted(files),
            }
        )
    return {"export_dir": str(export_root), "reports": out}
