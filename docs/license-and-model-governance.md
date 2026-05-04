# License and model governance

This document covers two related topics: the licenses of the runtime
dependencies, and the policy review every model file must pass before
it can be enabled in a deployment.

## Runtime dependency licenses

`care` itself is released under the license at
`LICENSE`. Every Python dependency declared in `pyproject.toml` is
listed in the SBOM with its license string:

```
care generate-sbom --output dist/sbom.json
```

The output's `licenses.by_package` map is the canonical license
report. The CI build runs the SBOM emitter and fails if any required
field is missing.

### Required at build time

| Package | License |
|---|---|
| `fastapi` | MIT |
| `pydantic` | MIT |
| `pypdfium2` | Apache-2.0 / BSD-3-Clause (per file) |
| `pillow` | HPND |
| `pyyaml` | MIT |

(`care generate-sbom` produces the authoritative list at build time.
The table above is illustrative.)

## Model governance

Optional model providers are governed individually because their
licenses vary widely. **Default behaviour: every optional provider is
disabled.**

| Provider | Default | Generative? | Hallucination risk? | Notes |
|---|---|---|---|---|
| `mock_ocr` | n/a | no | no | tests only |
| `noop` (OCR) | disabled | no | no | placeholder; emits no text |
| `onnxtr` | disabled | no | no | Apache-2.0 (provider) + Apache-2.0 (docTR weights via OnnxTR releases). **Recommended for printed crash-report forms.** Operator-supplied `*.onnx` weights — see `models/ocr/onnxtr/README.md`. |
| `paddleocr` | disabled | no | no | Apache-2.0; per-language pack license varies |
| `tesseract` | disabled | no | no | Apache-2.0; per-language `.traineddata` license varies |
| `regex` (PII) | enabled | no | no | n/a |
| `presidio` | disabled | no | no | MIT; bundled spaCy model carries its own license |
| `piiranha` | disabled | no | no | License-review-required, NOT bundled |
| `roberta_ner` (PII) | disabled | no | no | MIT (Jean-Baptiste/roberta-large-ner-english). General English NER for free-text PER/LOC/ORG. NOT bundled. |
| `openai_privacy_filter` (PII) | disabled | no | no | Apache-2.0 (openai/privacy-filter). 1.5B-param token classifier (50M active via MoE), eight PII labels including account numbers and secrets. ~2.8 GB. Needs `transformers>=5.6` (in `[ml]` extra). NOT bundled. |
| `mock_pii` | n/a | no | no | tests only |
| `kosmos25` | disabled | **yes** | **yes** | License-review-required, NOT bundled |
| `layoutlm` | disabled | no | no | License varies by variant — see "LayoutLM" section below. |
| `mock_vlm` | n/a | no | no | tests only |
| `hf_local` (LLM) | disabled | varies | varies | Local HF checkpoint; license varies. NOT bundled. Suggestion-only. |
| `openai` / `anthropic` / `gemini` (LLM) | disabled | yes | yes | Network required; vendor TOS apply. Refused in offline mode. License-review-required. |

### Activation policy

Before flipping `enabled: true` for any optional provider:

1. Read the provider's `models/.../README.md`.
2. Obtain and review the upstream license. Document the review
   outcome (date, reviewer, license terms) in your deployment's
   internal change log.
3. Place the model files under `models/<group>/<provider>/`.
4. Run `python scripts/compute_model_checksums.py <model_dir>` and
   pin the result alongside the model.
5. Run `care model-manifest --models-dir models`
   and confirm the new provider appears with `model_path_present: true`.
6. Edit `config.yaml` to set `enabled: true`.
7. Run `python scripts/verify_no_network.py` to confirm offline
   posture is unchanged.
8. Run the integration tests against synthetic fixtures.

### Generative providers

Kosmos-2.5 is generative and may hallucinate. Even when enabled, the
reconciler refuses to let VLM-only text drive image redaction, and
the QA gate blocks export when VLM and OCR conflict. Reviewers must
confirm before any generative-touched report is exported.

## LayoutLM

LayoutLM is an *optional* discriminative document-understanding model
from Microsoft. Variants and their licenses (verified on Hugging
Face model cards as of 2026-05-01):

| Variant                              | License            | Commercial use? |
|--------------------------------------|--------------------|-----------------|
| `microsoft/layoutlm-base-uncased`    | **MIT**            | yes             |
| `microsoft/layoutlmv2-base-uncased`  | CC BY-NC-SA 4.0    | **NO**          |
| `microsoft/layoutlmv3-base`          | CC BY-NC-SA 4.0    | **NO**          |

The plugin records the license on every model manifest. Loading a
non-commercial variant adds `LAYOUTLM_LICENSE_REVIEW_REQUIRED` to
`qa_flags_emitted_on_use`. Operators must review the variant license
against their deployment context (research vs commercial) before
enabling.

LayoutLM is suggestion-only — it never drives public export, never
drives PII redaction, never drives image redaction. Every report it
touches has `requires_human_review = True` until an operator
explicitly accepts a suggestion into a template (which exits the
LayoutLM pathway entirely; the new template is then evaluated like
any hand-authored one).

### Model file integrity

Per-file SHA-256 checksums are computed by the provider on load
(`Kosmos25Provider._compute_checksums`) and embedded in the runtime
manifest. They are also recorded by:

- `care model-manifest` (provider-aware report)
- `python scripts/compute_model_checksums.py <dir>` (single-dir,
  shell-friendly)
- `scripts/package_offline_installer.sh` (packaging-time snapshot)

A mismatch between a deployed model and its recorded checksums is
the operator's signal to stop and investigate.
