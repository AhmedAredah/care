# Security model

This document describes the runtime threat model and how the codebase
defends against each category. It is not a checklist — it explains
the *why* behind CARE's privacy and offline commitments.

## Threat model

`care` is operated by DOTs (or their suppliers) on
documents that contain real personal information. The software must:

1. Not exfiltrate PII to any external service.
2. Not write originals or unredacted text to any public-export location.
3. Not log raw PII.
4. Not silently downgrade safety (e.g. enabling a generative VLM by default).
5. Not let URL/path inputs reach disk regions outside the configured sandbox.

## Defenses

### Network

- **Default-on offline guard** (`care/core/offline_guard.py`)
  monkey-patches `socket.connect` so any outbound connect to a
  non-loopback host raises `OfflineGuardError`. The guard is engaged
  by `create_app()` at server start and by every CLI command that
  loads a provider. The `verify-offline` CLI subcommand audits this.
- **HF / Transformers offline env vars** (`HF_HUB_OFFLINE=1`,
  `TRANSFORMERS_OFFLINE=1`, `HF_DATASETS_OFFLINE=1`,
  `HF_HUB_DISABLE_TELEMETRY=1`, `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`)
  are set inside every HF-using provider's `load()` BEFORE any
  `transformers` import.
- **No telemetry / analytics / auto-update.** No code path opens a
  socket against a non-loopback target.

### Inputs

- **SHA-256 every input** at ingestion (`ingestion/hashing.py`). The
  hash becomes the report id and is the only client-visible identifier.
- **Path traversal guard** in `core/security.py::safe_join`. Every
  API report endpoint re-derives the served path via
  `safe_join(export_dir, "report_<id>", filename)`. URL inputs never
  reach `open()` directly.
- **Report id regex** (`^[0-9a-f]{16}$`) on every API path so even
  an attacker who controls the URL cannot inject `..` or absolute
  paths.

### Public exports

- **Only five files per allowed report**: `diagram.redacted.png`,
  `narrative.redacted.txt`, `narrative.redacted.json`, `manifest.json`,
  `qa.json`. Default config has `include_original_pdf=false`,
  `include_unredacted_text=false`, `include_debug_artifacts=false`,
  and the policy checker fails the build if any export module flips
  these.
- **Audit log fields strip raw text.** `redaction/audit.py` records
  only `entity_type`, `provider`, and offsets — never the matched
  text.
- **Fail-closed QA gate.** Any blocking flag prevents the exporter
  from writing.

### Logs

- **PII-redacting log filter** (`core/logging.py`). Known entity
  shapes are scrubbed before emit. The `logging.log_raw_pii` config
  flag is `false` by default; flipping it requires a deliberate
  config edit and is intended for local debug only.

### Plugins

- **Plugin allowlist via registry.** Unknown provider names raise
  `PluginNotFoundError`. There is no "load arbitrary class from a
  user-supplied path" code path.
- **Optional providers stay disabled by default.** Piiranha and
  Kosmos-2.5 are registered but `enabled_by_default = False`. The
  default `config.yaml` keeps them off.
- **VLM-only text never drives image redaction.** The reconciler
  (`document_ir/reconcile.py`) only attaches `AlternativeSource`
  entries to base words; bbox-less VLM text is recorded as a warning
  and never enters a redactable surface.

### API surface

- **127.0.0.1 binding by default.** `cli serve` refuses non-loopback
  hosts unless `--allow-non-loopback` is explicitly passed.
- **No raw OCR / VLM data on any endpoint.** The API exposes only the
  sanitized `ReportView` plus the redacted on-disk artifacts.
- **Review actions can't bypass QA.** `approve_report` returns 409
  when `qa_export_blocked` is true; review state is informational.

## What this software does NOT defend against

- A malicious operator with write access to `config.yaml`. Flipping
  `offline.enabled` to false defeats the network guard. Trust the
  operator + the change-review process.
- Side-channel leaks via system metrics or logs the operator
  configures themselves outside the app.
- Compromise of model files placed under `models/`. Per-file SHA-256
  manifests (Phase 7) let the operator verify integrity, but the
  chain of custody for the model itself is the operator's
  responsibility.
