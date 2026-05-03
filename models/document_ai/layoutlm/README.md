# LayoutLM model directory (placeholder)

This directory is a **placeholder**. No model binaries are committed
to this repository. The LayoutLM plugin (`care/document_ai/
providers/layoutlm_provider.py`) refuses to start unless this
directory contains a complete local checkpoint.

## What to place here

For `microsoft/layoutlm-base-uncased` (v1, MIT-licensed):

- `config.json`
- `pytorch_model.bin` **or** `model.safetensors`
- `tokenizer.json`
- `tokenizer_config.json`
- `vocab.txt`
- `special_tokens_map.json`

For `microsoft/layoutlmv3-base` (v3, CC BY-NC-SA 4.0):

- the same files plus `preprocessor_config.json` and the processor
  artifacts published with the v3 release

Download files **before** deployment using whatever your environment
permits (`huggingface_hub.snapshot_download` on a build host with
network, then ship the directory to the air-gapped target). The
plugin will never reach out to the Hub at runtime.

## License

- v1 (`microsoft/layoutlm-base-uncased`) — **MIT**.
  Commercial use permitted.
- v2 / v3 (`microsoft/layoutlmv2-*`, `microsoft/layoutlmv3-*`) —
  **CC BY-NC-SA 4.0 (NonCommercial)**. Review with legal before
  using on commercial or paid-deployment work. The plugin manifest
  emits `LAYOUTLM_LICENSE_REVIEW_REQUIRED` for any v2/v3 variant.

## Hash verification

After populating this directory, compute SHA-256s with:

```
care compute-model-checksums models/document_ai/layoutlm
```

Pin the hashes in your deployment manifest. The plugin records
per-file SHA-256s in its `model_checksums` manifest field; CI can
diff against the pinned set to detect tampering.

## Why this is optional

The pipeline is template-driven and fail-closed by default. LayoutLM
is **suggestion-only**:

- Region-detection results never replace the template-driven crop.
- LayoutLM output is gated by `LAYOUTLM_REQUIRES_REVIEW` so any
  report touched by it forces human review.
- LayoutLM cannot drive image redaction (`safe_for_image_redaction`
  is `False` in the manifest).

Disabled by default. To enable, edit `config.yaml`:

```yaml
document_ai:
  enabled: true
  provider_chain: [layoutlm]
  providers:
    layoutlm:
      enabled: true
      variant: layoutlm-base-uncased
      model_dir: ./models/document_ai/layoutlm
```
