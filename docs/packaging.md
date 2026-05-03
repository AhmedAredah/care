# Packaging

This document describes how to build the offline installer. It is the
counterpart to `docs/deployment.md` (which is for the operator).

## Build host requirements

- Linux x86_64 with **network access**.
- Python 3.11 (matching the target host).
- `bash`, `rsync`, `tar`, `sha256sum`.

The build host downloads wheels and emits the bundle; the air-gapped
host installs from the bundle. **No machine has both roles
simultaneously.**

## Steps

```
# 1. Resolve and download every Python wheel
bash scripts/build_wheelhouse.sh dist/wheelhouse

# 2. Generate the SBOM
bash scripts/generate_sbom.sh dist/sbom.json

# 3. (Optional) Drop vetted model files into models/ and record their checksums
python scripts/compute_model_checksums.py models/document_ai/kosmos-2.5 \
    --output models/document_ai/kosmos-2.5/model-checksums.json

# 4. Emit the per-provider model manifest
python -m care.cli model-manifest \
    --models-dir models \
    --output dist/model-manifest.json

# 5. Build the bundle
bash scripts/package_offline_installer.sh
# → dist/care-<version>.tar.gz
# → dist/care-<version>/  (staging dir)
```

The packaged tarball includes:

```
care-<version>/
  app/                  Python package (no __pycache__/, no .pyc)
  frontend/             local-only HTML/CSS/JS
  templates/            template YAMLs (synthetic only)
  config/               config.yaml + .env.example
  scripts/              operator scripts
  docs/                 every doc under docs/
  wheelhouse/           every Python wheel + wheelhouse.sha256.json
  models/               provider README placeholders only
  sbom.json             care.sbom.v1 document
  checksums.sha256      flat sha256 list for every file in the bundle
  INSTALL.md            copy of docs/deployment.md
  LICENSE
```

## What's NOT in the bundle

- Real model files. The operator places them after install.
- Real DOT data or any PII. Fixtures are synthetic and live in `tests/`.
- Build-host-specific paths or caches.
- Cloud SDKs. Cloud / network providers are forbidden by policy.

## Verifying a built bundle

```
# After running package_offline_installer.sh:
cd dist/care-<version>
sha256sum -c checksums.sha256
python scripts/verify_no_network.py
python scripts/scan_frontend_external_assets.py frontend
```

All three should exit 0.

## Re-using a wheelhouse

The wheelhouse is a flat collection of `*.whl` plus a
`wheelhouse.sha256.json` manifest. You can reuse it across multiple
bundles for the same Python version + arch.

If you migrate to a new Python minor version, rebuild the wheelhouse
from scratch — manylinux tags are version-sensitive.
