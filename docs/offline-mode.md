# Offline Mode

`care` runs **fully offline by default**. Nothing about the
default build, default config, default plugin chain, or default frontend
should require internet access. This document describes how the offline
guarantee is enforced and how to verify it.

## What offline mode blocks

When offline mode is enabled (`offline.enabled: true`, the default), the
application:

- Sets the Hugging Face / Transformers offline environment variables:
  - `HF_HUB_OFFLINE=1`
  - `TRANSFORMERS_OFFLINE=1`
  - `HF_DATASETS_OFFLINE=1`
  - `HF_HUB_DISABLE_TELEMETRY=1`
  - `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`
- Monkey-patches `socket.socket.connect` so any non-loopback connect
  attempt raises `OfflineGuardError` (see `care/core/offline_guard.py`).
- Refuses to load plugins whose declared `requires_network` is `true`.
- Refuses to load Hugging Face / Transformers models from a remote model
  ID; only local filesystem paths with `local_files_only=True` are allowed.
- Refuses to start if the configured plugin chain references an unknown
  or network-requiring provider.

## Loopback is allowed

Connections to `127.0.0.1`, `::1`, and `localhost` are allowed so that the
local FastAPI server, the local frontend, and intra-process socket pairs
keep working.

## How to verify

- Run `python scripts/governance_check.py`.
- Run `pytest tests/offline` — every test in that directory monkey-patches
  network primitives and asserts that no external connection is attempted.
- Run `care verify-offline` (CLI, Phase 6).

## Disabling offline mode

Disabling offline mode is **not recommended for DOT deployments**. If you
must, set `offline.enabled: false` in `config.yaml`. Plugins that require
network access will still be rejected unless they explicitly declare
`requires_network: true` and the operator has accepted the warning.
