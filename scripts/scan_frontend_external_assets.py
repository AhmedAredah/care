#!/usr/bin/env python3
"""Scan frontend/ for non-loopback URLs.

Used by CI and the CLI's `scan-frontend-assets` subcommand. Emits a JSON
report listing every offending file/match and exits non-zero if any are
found.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXTERNAL_URL_RE = re.compile(
    r"""(?i)(https?://(?!127\.0\.0\.1|localhost)|//(?!127\.0\.0\.1|localhost))"""
)

DEFAULT_FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"


def scan(frontend_dir: Path) -> dict:
    findings: list[dict[str, object]] = []
    files_scanned = 0
    for path in sorted(frontend_dir.rglob("*")):
        if path.suffix.lower() not in {".html", ".css", ".js"}:
            continue
        files_scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        for m in EXTERNAL_URL_RE.finditer(text):
            findings.append(
                {
                    "file": str(path.relative_to(frontend_dir)),
                    "match": m.group(0),
                    "offset": m.start(),
                }
            )
    return {
        "frontend_dir": str(frontend_dir),
        "files_scanned": files_scanned,
        "external_url_count": len(findings),
        "findings": findings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "frontend_dir",
        nargs="?",
        default=str(DEFAULT_FRONTEND_DIR),
        help="path to frontend/ (default: repo frontend/)",
    )
    args = parser.parse_args(argv)
    target = Path(args.frontend_dir).resolve()
    if not target.exists():
        print(f"error: {target} does not exist", file=sys.stderr)
        return 2
    payload = scan(target)
    print(json.dumps(payload, indent=2))
    return 1 if payload["external_url_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
