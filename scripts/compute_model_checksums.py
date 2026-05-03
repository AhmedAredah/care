#!/usr/bin/env python3
"""Compute SHA-256 checksums for every file under one model directory.

Used by `package_offline_installer.sh` to record what's bundled and by
operators to verify model integrity before enabling a provider. Output
matches the `model_checksums` field embedded in each provider's
runtime manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def compute_checksums(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for f in sorted(root.rglob("*")):
        if not f.is_file():
            continue
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        out[str(f.relative_to(root))] = h.hexdigest()
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", help="path to a single provider's model directory")
    parser.add_argument("--output", help="write JSON to this file (default: stdout)")
    args = parser.parse_args(argv)

    target = Path(args.model_dir).resolve()
    if not target.exists() or not target.is_dir():
        print(f"error: {target} does not exist or is not a directory", file=sys.stderr)
        return 2

    payload = {
        "format": "care.model_checksums.v1",
        "model_dir": str(target),
        "file_count": 0,
        "checksums": compute_checksums(target),
    }
    payload["file_count"] = len(payload["checksums"])
    out = json.dumps(payload, indent=2)
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
