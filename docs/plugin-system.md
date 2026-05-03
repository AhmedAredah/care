# Plugin System

The core pipeline of `care` does **not** depend on any
specific OCR engine, PII model, VLM/document-AI model, PDF backend,
template detector, redaction strategy, or exporter. It depends only on
abstract interfaces and registries declared in `care/`.

## Plugin categories

| Category               | Base class                              | Registry                              |
|------------------------|-----------------------------------------|---------------------------------------|
| Traditional OCR        | `care.ocr.base.OCRProvider`      | `care.ocr.registry`            |
| VLM / document-AI      | `care.document_ai.base.DocumentAIProvider` | `care.document_ai.registry` |
| PII detection          | `care.pii.base.PIIDetectionProvider` | `care.pii.registry`        |
| PDF / image backends   | `care.pdf.base.PDFImageBackend`  | (Phase 2)                             |
| Templates              | YAML in `templates/`                    | `care.templates.registry` (Phase 3) |
| Redactors              | `care.redaction` (Phase 4)       | (Phase 4)                             |
| Exporters              | `care.export` (Phase 4)          | (Phase 4)                             |
| QA / review policies   | `care.review` (Phase 3)          | (Phase 3)                             |

## Required plugin attributes

Every plugin must expose:

- `name`, `version`, `provider_type`
- `requires_network` (must be `false` for default-enabled plugins)
- `enabled_by_default` (optional providers must be `false`)
- `load(config)`, `healthcheck()`, `get_model_manifest()`, `close()`

`get_model_manifest()` must return at least:

- provider name / version / type
- model name / version / path
- model checksums
- license
- `requires_network`
- `enabled_by_default`
- `safe_for_offline_use`
- `generative` and `may_hallucinate` (true for VLMs)
- `provides_bboxes`
- `safe_for_image_redaction`

## Registry rules

- Registries only know about plugins explicitly registered in code or
  declared in `config.yaml`.
- Unknown plugin names are rejected.
- Plugins that declare `requires_network: true` are rejected when
  offline mode is enabled.
- Optional plugins (Piiranha, Kosmos-2.5, future VLMs) must be
  disabled by default.

## Adding a plugin

1. Subclass the relevant base class.
2. Implement every abstract method.
3. Populate `get_model_manifest()` with model paths and checksums.
4. Register the class in the relevant `registry.py` module.
5. Reference the plugin in `config.yaml` under the matching section.
6. Add tests under `tests/unit/` and `tests/offline/`.
7. Run `python scripts/governance_check.py`.
