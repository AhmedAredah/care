# Kosmos-2.5 (OPTIONAL — disabled by default)

> **Generative + hallucination-prone.** This provider must remain
> disabled until the deployment has documented review SLAs for any
> VLM-derived output.

`care.document_ai.providers.kosmos25_provider` loads
`microsoft/kosmos-2.5` in `local_files_only=True` mode. Place model
and processor files together under:

```
models/document_ai/kosmos-2.5/
  config.json
  tokenizer.json
  processor_config.json
  model.safetensors  (or shards)
```

The provider sets every HF offline env var, refuses if `allow_network`
is true, and computes per-file SHA-256 checksums on load — these are
embedded into the provider manifest and recorded by
`scripts/compute_model_checksums.py`.

VLM output without bounding boxes NEVER drives image redaction (see
`care.document_ir.reconcile`). The QA gate blocks export when
VLM and OCR conflict.

## Required checksums

Run:

```
python scripts/compute_model_checksums.py models/document_ai/kosmos-2.5
```

and pin the resulting `model-checksums.json` alongside this README.

## License

Kosmos-2.5: see the original model card. Verify before deployment.
