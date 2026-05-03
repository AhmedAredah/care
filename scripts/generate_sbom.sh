#!/usr/bin/env bash
# Emit the care SBOM JSON.
#
# Wraps `python -m care.cli generate-sbom` so packaging
# tooling has a stable, shell-friendly entry point. Output path
# defaults to ./dist/sbom.json.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_PATH="${1:-${REPO_ROOT}/dist/sbom.json}"
MODELS_DIR="${MODELS_DIR:-${REPO_ROOT}/models}"
PYTHON="${PYTHON:-python3}"

mkdir -p "$(dirname "$OUT_PATH")"

cd "$REPO_ROOT"
"$PYTHON" -m care.cli generate-sbom \
    --output "$OUT_PATH" \
    --models-dir "$MODELS_DIR"

echo ">>> SBOM written to $OUT_PATH"
