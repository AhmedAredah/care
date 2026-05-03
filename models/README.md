# Model files

This directory holds **local model files** used by the optional
plugin-based providers. Nothing here is committed to the repository —
operators must place model files manually as part of an offline
deployment.

## Layout

```
models/
  ocr/
    paddleocr/    (det/, rec/, cls/)
    tesseract/    (tessdata/)
  pii/
    presidio/
    piiranha/
  document_ai/
    kosmos-2.5/
```

Each provider directory MUST be self-contained: weights, tokenizers,
processor configs, and `LICENSE` text live alongside the model. The
default config refers to these paths via `models_dir` and never
attempts a download.

## Verifying integrity

After placing model files, compute and record their checksums:

```
python -m care.cli compute-model-checksums models/document_ai/kosmos-2.5
python -m care.cli model-manifest --models-dir models > model-manifest.json
```

The same `compute-model-checksums` is also exposed as
`scripts/compute_model_checksums.py` for use without the runtime venv.

## Activation

Optional providers (`piiranha`, `kosmos25`) STAY DISABLED BY DEFAULT.
Edit `config.yaml` only after the operator has reviewed each model's
license — see `docs/license-and-model-governance.md`.
