# Architecture

`care` is a single-process, plugin-based pipeline that
turns crash report PDFs/images into redacted, audit-friendly export
artifacts. It is designed for air-gapped DOT deployments: nothing in
the default configuration touches the network.

## Top-level layout

```
care/
    core/               offline guard, config, logging, paths, errors
    ingestion/          file scan, hashing, manifest
    pdf/                pypdfium2-backed inspect/render/native-text
    ocr/                provider interface + chain (mock_ocr, paddleocr, …)
    document_ai/        VLM/document-AI provider interface (kosmos25, …)
    pii/                provider interface + recognizers (regex, presidio, piiranha)
    document_ir/        provider-neutral DocumentIR + reconciler
    templates/          YAML schema, registry, scoring, detector
    extraction/         diagram + narrative extractors
    redaction/          text + image redactors, audit emitters
    review/             QA gate, fail-closed logic
    export/             public exporter (5 redacted files)
    workers/            pipeline orchestration
    services/           in-memory job + report store
    api/                FastAPI routes (Phase 6)
    cli/                argparse CLI (Phase 6)
    audit/              SBOM + model manifest emitters (Phase 7)
frontend/               local-only HTML/CSS/JS UI (Phase 6)
```

## Pipeline stages

The pipeline (`care/workers/pipeline.py::run_pipeline`) walks
each input through these stages, in order:

1. **Ingestion** — scan dir, SHA-256 every file, build a file manifest.
2. **Inspection** — PDF text-layer presence, image-only flag, page count, dimensions.
3. **Rendering** — only when needed for OCR or diagram extraction.
4. **Native-text extraction** — pypdfium2 char-level bboxes, image-space at the configured DPI.
5. **OCR provider chain** — first-success fallback across `cfg.ocr.provider_chain`.
6. **VLM / document-AI** — only when `document_ai.enabled` is true; otherwise skipped entirely.
7. **DocumentIR reconciliation** — merges native + OCR + VLM into one DocumentIR with provenance.
8. **Template detection** — anchors + form-number regex + page-count + layout scoring.
9. **Diagram extraction** — normalised bbox + redactable image crop.
10. **Narrative extraction** — anchor-bounded text slice.
11. **PII detection** — provider chain (regex by default).
12. **QA gate** — fail-closed flags & blocking reasons.
13. **Export** — five redacted files, only when QA allows.

Every stage has a unit test slice; the integration tests in
`tests/integration/` exercise the full pipeline end-to-end.

## Data flow

```
filesystem  →  ingestion  →  inspection  →  render
                    ↓                          ↓
                file SHA              native-text  ←  OCR chain
                                        ↓              ↓
                                          DocumentIR  ←  VLM (optional)
                                              ↓
                              template detect  →  diagram + narrative
                                              ↓
                                        PII detection
                                              ↓
                                          QA gate
                                              ↓
                                    redaction + exporter
                                              ↓
                                       exports/report_<sha>/...
```

All cross-stage data lives in pydantic models under `document_ir/` and
dataclasses under `extraction/`, `pii/`, and `review/`. No global
state.

## Plugin boundaries

The core pipeline imports interfaces and registries:

```python
from care.ocr.base       import OCRProvider
from care.ocr.registry   import get_registry as get_ocr_registry
from care.document_ai.base     import DocumentAIProvider
from care.pii.base       import PIIDetectionProvider
```

It NEVER imports `paddleocr`, `tesseract`, `presidio_analyzer`,
`piiranha`, or `transformers` directly. Concrete provider modules
live under `care/<group>/providers/` and only load when
their entry in `config.yaml` is enabled.

## Offline guard

`care/core/offline_guard.py` monkey-patches `socket.connect`
and `socket.create_connection` so non-loopback connects raise
`OfflineGuardError`. It also sets the five HF / Transformers offline
env vars at process start. The guard is engaged by default; the
`/api/offline/status` endpoint reports its current state.

## Fail-closed gate

`care/review/qa_flags.py::build_qa_report` is the single chokepoint
for export safety. Any of these conditions blocks export:

- template UNKNOWN or below confidence threshold
- diagram region uncertain
- narrative anchors not found / empty
- PII could not be mapped to image coordinates (`PII_UNMAPPED`)
- VLM output disagrees with OCR (`VLM_OUTPUT_CONFLICTS_WITH_OCR`)

The exporter (`care/export/exporter.py::export_artifact`) checks
`qa.export_blocked` before doing anything; blocked reports produce no
public artifacts.
