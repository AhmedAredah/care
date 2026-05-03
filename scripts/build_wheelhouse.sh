#!/usr/bin/env bash
# Build a local wheelhouse of every runtime + dev dependency.
#
# Run this on a NETWORKED build host. The resulting wheelhouse/ tarball
# is then carried across to the air-gapped deployment host, where
# `package_offline_installer.sh` consumes it.
#
# Inputs:
#   $1  output dir for wheels (default: ./dist/wheelhouse)
# Env:
#   PYTHON  python interpreter to resolve against (default: python3)
#
# This script never runs on the target host.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${1:-${REPO_ROOT}/dist/wheelhouse}"
PYTHON="${PYTHON:-python3}"

mkdir -p "$OUT_DIR"

echo ">>> using interpreter: $($PYTHON --version)"
echo ">>> wheelhouse output: $OUT_DIR"

# Resolve runtime + dev groups straight from pyproject.toml. We use
# `pip download` to walk the dependency graph and pull every wheel.
"$PYTHON" -m pip download \
    --dest "$OUT_DIR" \
    --no-binary=:none: \
    --prefer-binary \
    --no-cache-dir \
    -r <("$PYTHON" - <<'PY'
import sys, tomllib
from pathlib import Path
data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
deps = list(data.get("project", {}).get("dependencies", []))
for group in data.get("dependency-groups", {}).values():
    deps.extend(group)
for d in deps:
    print(d)
PY
)

echo ">>> wheels collected:"
ls -1 "$OUT_DIR" | sed 's/^/    /'

# Emit a SHA-256 manifest so the offline installer can verify integrity.
"$PYTHON" - <<PY
import hashlib, json, sys
from pathlib import Path
out_dir = Path("$OUT_DIR")
checksums = {}
for wheel in sorted(out_dir.iterdir()):
    if not wheel.is_file():
        continue
    h = hashlib.sha256()
    with wheel.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    checksums[wheel.name] = h.hexdigest()
manifest = out_dir / "wheelhouse.sha256.json"
manifest.write_text(json.dumps({
    "format": "care.wheelhouse.v1",
    "wheel_count": len(checksums),
    "checksums": checksums,
}, indent=2), encoding="utf-8")
print(f">>> wrote {manifest}")
PY

echo ">>> done. Carry $OUT_DIR to the air-gapped host."
