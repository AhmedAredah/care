# No-network guarantee

CARE guarantees that no code path in `care` contacts a non-loopback
host at runtime in the default offline configuration. This document
explains how that guarantee is implemented and how to audit it.

## Implementation

### Process-level guard

`care/core/offline_guard.py::enable()` monkey-patches:

- `socket.socket.connect`
- `socket.create_connection`

so any connect to an address other than `127.0.0.1`, `localhost`, or
`::1` raises `OfflineGuardError` before reaching the OS. The guard is
idempotent — calling `enable()` twice is safe.

### Hugging Face / Transformers env

Every provider that imports `transformers` calls
`os.environ.setdefault(key, value)` for the five HF offline env vars
**before** the import. Even if the global guard is disabled, HF will
not attempt a download.

### Optional provider gating

Optional providers (Piiranha, Kosmos-2.5) are registered but disabled.
Their `load()` raises:

- `ConfigError` if `allow_network: true` or `local_files_only: false`
  is set
- `OfflineGuardError` if the local model directory is missing

A misconfigured deployment fails at load time rather than at
inference time.

### Frontend

The frontend uses `<script src="/js/...">` and `<link href="/css/...">`
only. CSS uses no `@import` and no `url(http...)`. JS uses `fetch()`
against `/api/*` paths only. The policy checker
(`scripts/governance_check.py::check_frontend_no_external_assets`) and
the standalone scanner
(`scripts/scan_frontend_external_assets.py`) both fail the build if
an external URL appears in any HTML/CSS/JS file.

## Auditing

Three independent tools verify the guarantee:

1. **Static.** `scripts/governance_check.py` rejects any external URL
   in `frontend/`. `scripts/scan_frontend_external_assets.py` scans
   the same files standalone.
2. **Runtime.** `scripts/verify_no_network.py`:
   - confirms the five HF env vars are set
   - enables the offline guard
   - tries to connect to `8.8.8.8:53` and asserts `OfflineGuardError`
   - imports every registered provider class without contacting the
     network
3. **CI / policy tests.** `tests/offline/` includes
   `test_offline_guard.py` and `test_pipeline_offline.py` that run
   the full pipeline with the guard engaged and a stubbed
   `socket.connect` that fails on non-loopback.

## Loopback exceptions

The local API binds to `127.0.0.1`. The frontend talks to it on the
same origin. The guard explicitly allows loopback so this works.
There is no codepath that allows the guard to be bypassed for any
non-loopback target.

## When NOT to disable the guard

Never. If a deployment requires updated model files, transfer them
out-of-band and re-bundle (`build_wheelhouse.sh` +
`package_offline_installer.sh`). The runtime should never be the
machine that does the downloading.

## LayoutLM (Phase 10) — additional offline checks

Each Hugging Face / Transformers plugin (Kosmos-2.5, LayoutLM)
re-applies the offline env-var set in its own `load()` so it never
trusts that some other layer set them first. The plugin also passes
`local_files_only=True` to every `from_pretrained` call. A missing
`model_dir` raises `OfflineGuardError` rather than degrading to a
download attempt. `allow_network: true` and `local_files_only: false`
are explicit `ConfigError`s — the plugin refuses to start.
