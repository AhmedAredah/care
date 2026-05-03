#!/usr/bin/env bash
# Build the offline installer tarball.
#
# Layout produced under ./dist/care-<version>/:
#
#   care-<version>/
#     app/                  — the backend/ Python package (no .pyc, no caches)
#     frontend/             — local-only HTML/CSS/JS
#     templates/            — template YAMLs
#     config/               — config.yaml (and example variants)
#     scripts/              — operator scripts (this file + verify_no_network.py + …)
#     docs/                 — operator docs
#     wheelhouse/           — Python wheels collected by build_wheelhouse.sh
#     models/               — provider READMEs only; real model files are
#                             placed by the operator after install
#     sbom.json             — care.sbom.v1
#     checksums.sha256      — flat sha256 list for every file in the bundle
#     INSTALL.md            — copy of docs/deployment.md
#
# This script does NOT touch the network. It assumes
# `build_wheelhouse.sh` and `generate_sbom.sh` have already been run.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST_DIR="${REPO_ROOT}/dist"
PYTHON="${PYTHON:-python3}"
WHEELHOUSE_SRC="${WHEELHOUSE_SRC:-${DIST_DIR}/wheelhouse}"
SBOM_SRC="${SBOM_SRC:-${DIST_DIR}/sbom.json}"

VERSION="$("$PYTHON" - <<'PY'
import tomllib, pathlib
data = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
print(data["project"]["version"])
PY
)"

BUNDLE_NAME="care-${VERSION}"
BUNDLE_DIR="${DIST_DIR}/${BUNDLE_NAME}"

rm -rf "$BUNDLE_DIR"
mkdir -p "$BUNDLE_DIR"

echo ">>> staging app code"
mkdir -p "$BUNDLE_DIR/app"
rsync -a --delete \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    "$REPO_ROOT/backend/" "$BUNDLE_DIR/app/"

echo ">>> staging frontend"
rsync -a --delete "$REPO_ROOT/frontend/" "$BUNDLE_DIR/frontend/"

echo ">>> staging templates"
rsync -a --delete "$REPO_ROOT/templates/" "$BUNDLE_DIR/templates/"

echo ">>> staging configs"
mkdir -p "$BUNDLE_DIR/config"
cp "$REPO_ROOT/config.yaml" "$BUNDLE_DIR/config/config.yaml"
[ -f "$REPO_ROOT/.env.example" ] && cp "$REPO_ROOT/.env.example" "$BUNDLE_DIR/config/.env.example" || true

echo ">>> staging scripts"
mkdir -p "$BUNDLE_DIR/scripts"
cp "$REPO_ROOT/scripts/"*.{sh,py} "$BUNDLE_DIR/scripts/" 2>/dev/null || true

echo ">>> staging docs"
mkdir -p "$BUNDLE_DIR/docs"
cp "$REPO_ROOT/docs/"*.md "$BUNDLE_DIR/docs/"
cp "$REPO_ROOT/docs/deployment.md" "$BUNDLE_DIR/INSTALL.md" 2>/dev/null || true
cp "$REPO_ROOT/LICENSE" "$BUNDLE_DIR/LICENSE" 2>/dev/null || true

echo ">>> staging desktop assets (Phase 14)"
if [ -d "$REPO_ROOT/assets" ]; then
    mkdir -p "$BUNDLE_DIR/assets"
    rsync -a --delete "$REPO_ROOT/assets/" "$BUNDLE_DIR/assets/"
fi

echo ">>> staging model placeholders"
mkdir -p "$BUNDLE_DIR/models"
rsync -a --include '*/' --include '*.md' --exclude '*' \
    "$REPO_ROOT/models/" "$BUNDLE_DIR/models/"

if [ -d "$WHEELHOUSE_SRC" ]; then
    echo ">>> staging wheelhouse from $WHEELHOUSE_SRC"
    mkdir -p "$BUNDLE_DIR/wheelhouse"
    rsync -a --delete "$WHEELHOUSE_SRC/" "$BUNDLE_DIR/wheelhouse/"
else
    echo ">>> WARNING: $WHEELHOUSE_SRC missing — run build_wheelhouse.sh first"
fi

if [ -f "$SBOM_SRC" ]; then
    cp "$SBOM_SRC" "$BUNDLE_DIR/sbom.json"
else
    echo ">>> WARNING: $SBOM_SRC missing — run generate_sbom.sh first"
fi

echo ">>> computing flat checksum list"
"$PYTHON" - <<PY
import hashlib
from pathlib import Path
bundle = Path("$BUNDLE_DIR")
out = []
for p in sorted(bundle.rglob("*")):
    if not p.is_file():
        continue
    if p.name == "checksums.sha256":
        continue
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    rel = p.relative_to(bundle)
    out.append(f"{h.hexdigest()}  {rel}")
(bundle / "checksums.sha256").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"   {(bundle / 'checksums.sha256')}: {len(out)} files")
PY

echo ">>> creating tarball"
tar -C "$DIST_DIR" -czf "${DIST_DIR}/${BUNDLE_NAME}.tar.gz" "$BUNDLE_NAME"

echo ">>> done."
echo "   bundle dir: $BUNDLE_DIR"
echo "   tarball   : ${DIST_DIR}/${BUNDLE_NAME}.tar.gz"
