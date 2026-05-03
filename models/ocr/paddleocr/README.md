# PaddleOCR models (placeholder)

PaddleOCR is loaded by `care.ocr.providers.paddleocr_provider`
**only** when `enabled: true` is set in `config.yaml` and the three
local model directories below are present:

```
models/ocr/paddleocr/det/
models/ocr/paddleocr/rec/
models/ocr/paddleocr/cls/
```

Each subdirectory must contain the inference files PaddleOCR's
`PaddleOCR(...)` constructor expects (`inference.pdmodel`,
`inference.pdiparams`, etc.). The provider runs with
`use_gpu=False`, `lang="en"` (or the configured locale), and
**never** triggers a model download.

## Required checksums

After placing files, run:

```
python scripts/compute_model_checksums.py models/ocr/paddleocr
```

and store the output alongside the model files. The packaging script
(`scripts/package_offline_installer.sh`) will refuse to bundle a model
directory whose computed manifest disagrees with the recorded one.

## License

PaddleOCR is Apache-2.0. Operators are responsible for verifying the
license of any third-party language packs.
