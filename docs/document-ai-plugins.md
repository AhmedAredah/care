# Document-AI / VLM Plugins

`care` distinguishes between two kinds of "document
reading" providers:

1. **Traditional OCR** (`provider_type: "traditional_ocr"`) — engines
   such as PaddleOCR or Tesseract that produce word/line tokens with
   tight bounding boxes and confidence scores. Output is non-generative
   and safe for image redaction when bbox quality is good.
2. **VLM / document-AI** (`provider_type: "vlm_document_parser"`) —
   multimodal models such as Kosmos-2.5, GOT-OCR, Nougat, Donut, or
   PaddleOCR-VL that read whole pages and emit text, markdown, or
   spatial tokens. Output is generative and may hallucinate.

Both kinds are plugins. The core pipeline never imports a specific
provider; it depends on `OCRProvider` and `DocumentAIProvider`.

## Why the distinction matters

- VLM output is **never** the sole driver of image redaction unless it
  ships reliable bounding boxes that pass mapping checks.
- VLM output is **never** silently used as the final narrative — the
  reconciler (Phase 5) prefers verbatim native PDF text or traditional
  OCR text when available.
- VLM markdown output is permitted as a *candidate signal* for section
  detection, narrative boundaries, and reading-order correction.
- VLM-only template detection requires human review.
- Generative output without confidence scores is treated as low
  confidence and routed to review.

## Kosmos-2.5

Kosmos-2.5 is implemented (Phase 5) as an *optional* provider:

- Disabled by default (`document_ai.providers.kosmos25.enabled: false`).
- Loads only from `model_dir` on local disk.
- Passes `local_files_only=True` to Transformers.
- Respects `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`, and
  `HF_DATASETS_OFFLINE=1`.
- Fails closed if any model file is missing — never falls back to a
  remote download.
- Records model path, revision, and per-file SHA-256 in its manifest.

## LayoutLM plugin (Phase 10, optional)

`care/document_ai/providers/layoutlm_provider.py` wraps
Microsoft LayoutLM (v1 / v2 / v3) for **suggestion-only** use.

- **Disabled by default.** Registered in the document-AI registry but
  `enabled: false` in `config.yaml`.
- **Local-only, offline-only.** Refuses `allow_network: true` and
  `local_files_only: false` at load time. Re-applies the Hugging Face
  offline env vars (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`,
  `HF_DATASETS_OFFLINE=1`, `HF_HUB_DISABLE_TELEMETRY=1`,
  `HF_HUB_DISABLE_IMPLICIT_TOKEN=1`) regardless of the global guard.
- **Fail-closed on missing files.** A missing `model_dir` raises
  `OfflineGuardError` rather than attempting a download.
- **Discriminative, not generative.** `generative_model: False`,
  `hallucination_risk: False`. The model produces region labels with
  bounding boxes, not free text.
- **Suggestion-only output.** Does not replace template-driven
  extraction, does not drive PII redaction, does not drive image
  redaction (`safe_for_image_redaction: False`).
- **Always review-gated.** Any QA report carrying a `LAYOUTLM_*` flag
  forces `requires_human_review = True` (handled by the QA gate via
  `REVIEW_REQUIRED_QA_FLAGS`). Operators can promote a suggestion
  into a template through the builder, which exits the LayoutLM
  pathway entirely.
- **License gating.** v1 (`microsoft/layoutlm-base-uncased`) is MIT;
  v2 / v3 (`microsoft/layoutlmv*`) are **CC BY-NC-SA 4.0**. Loading a
  non-commercial variant emits `LAYOUTLM_LICENSE_REVIEW_REQUIRED` in
  the manifest's `qa_flags_emitted_on_use`.

### When to use it

- **Region suggestion** in the template builder ("here's where the
  diagram probably is on this form — accept into the template?").
- **Fallback candidate generation** when no template scores above
  the confidence threshold; the LayoutLM-suggested regions are
  recorded as candidates only and the report is fail-closed pending
  review.
- **QA second opinion** — flag mismatches between LayoutLM's region
  proposals and the template's declared regions
  (`LAYOUTLM_CONFLICT_WITH_TEMPLATE`).

LayoutLM is **never** the primary extractor. The pipeline keeps
template-driven extraction as the system of record.

## Adding a future VLM plugin

1. Subclass `DocumentAIProvider`.
2. Set `generative_model: True` and `hallucination_risk: True`.
3. Implement `image_to_spatial_text` and/or `image_to_markdown`.
4. Convert outputs into DocumentIR-compatible structures with
   provenance recorded on every token, section, and region.
5. Register the plugin and add an entry under
   `document_ai.providers.<name>` in `config.yaml`, **disabled by
   default**.
6. Add tests covering: disabled-by-default behavior, local-files-only
   loading, no-network during load, manifest content, and behavior
   when the model returns text without bounding boxes.
