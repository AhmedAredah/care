# `openai/privacy-filter` model files

This directory is the local checkpoint location for the
[OpenAI Privacy Filter](https://huggingface.co/openai/privacy-filter)
model, used by the optional `openai_privacy_filter` PII provider.

**This directory ships empty.** CARE never bundles model weights —
operators provide their own copies. Drop the files listed below into
this directory before flipping `openai_privacy_filter.enabled: true`
in `config.yaml`.

## License

**Apache-2.0.** Commercial use is permitted. No license-review-required
flag — operators may deploy without legal sign-off (though a routine
license review is still recommended).

## Required files

The provider's `WEIGHT_MARKERS` only requires `config.json`, but the
HF `pipeline("token-classification", ...)` loader needs the full set
below to actually run:

| File | Size | Purpose |
|---|---|---|
| `config.json` | ~3 kB | Model architecture metadata. Required marker. |
| `model.safetensors` | ~2.8 GB | Model weights. |
| `tokenizer.json` | ~28 MB | Fast tokenizer state. |
| `tokenizer_config.json` | <1 kB | Tokenizer settings. |
| `viterbi_calibration.json` | <1 kB | Optional Viterbi decoder calibration. CARE does not use it via the standard `pipeline()` path; download it for parity with the upstream repo. |

Total disk footprint: **~2.84 GB**.

The `onnx/` and `original/` directories in the upstream repo are
**not needed** by CARE — skip them (they add ~14 GB).

## Download

### Online host (one-shot fetch via `huggingface-cli`)

```bash
huggingface-cli download openai/privacy-filter \
    --local-dir models/pii/openai-privacy-filter \
    --include "config.json" "model.safetensors" "tokenizer*" "viterbi_calibration.json"
```

### Air-gapped host

1. On a connected workstation, run the `huggingface-cli download`
   command above.
2. Compute integrity hashes:
   ```bash
   uv run python scripts/compute_model_checksums.py \
       models/pii/openai-privacy-filter
   ```
3. Copy the directory (preserving the layout) to the air-gapped
   target's `models/pii/openai-privacy-filter/`.
4. Recompute checksums on the target and confirm they match.

## Runtime requirements

The model class `OpenAIPrivacyFilterForTokenClassification` was added
in **transformers v5.6.0** (April 22, 2026). CARE's `[ml]` extra
already pins `transformers>=5.6` so a fresh `uv sync --extra ml`
gives you a compatible version.

CPU inference works but is slow on the 1.5B-param backbone (50M
active per token via MoE routing). A single GPU or Apple Silicon
device is recommended for batch processing.

## Enabling the provider

After the files are in place, edit `config.yaml`:

```yaml
pii:
  provider_chain:
    - regex
    - openai_privacy_filter   # add to chain
  providers:
    openai_privacy_filter:
      enabled: true            # flip from false
      model_dir: ./models/pii/openai-privacy-filter
      min_confidence: 0.85
      label_map: {}
```

Run the manifest emitter to confirm the provider is wired:

```bash
care model-manifest --models-dir models
```

The provider should appear with `model_path_present: true`.

## Tuning

- `min_confidence` (default 0.85) — privacy-filter typically scores
  detections at 0.99+, so this default lets nearly every prediction
  through. Raise it if you see false positives; lower it for a more
  recall-first chain.
- `label_map` — override the default label-to-`ENTITY_TYPE` mapping.
  See `care/pii/providers/openai_privacy_filter_provider.py` for the
  defaults. Set a value to `null` to drop a label entirely.

## Limitations (per upstream model card)

- Banded attention has an effective window of ~257 tokens. Crash-report
  narratives fit comfortably; long concatenated documents may have
  fragmented span boundaries.
- Performance drops on non-English text. Crash reports in this
  project's scope are English; this is not a current concern.
- Fine-grained label policy (which 8 labels exist) is fixed at training
  time. To change the label inventory, fine-tune the model upstream.

## When NOT to use it

Per OpenAI's model card, the privacy filter is **not** a sufficient
single-layer redactor for high-risk domains (medical, legal,
financial) without human review. CARE already gates exports on
`PII_UNMAPPED` and the QA review queue, so this provider remains a
useful component of the chain. But it should never be the only
detector — keep `regex` in the chain and surface uncertain reports to
human review.
