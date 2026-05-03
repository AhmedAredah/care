# Tesseract tessdata (placeholder)

`care.ocr.providers.tesseract_provider` loads a local
`tesseract` binary plus a `tessdata_dir` of language data files:

```
models/ocr/tesseract/tessdata/eng.traineddata
models/ocr/tesseract/tessdata/...
```

The provider invokes the binary with `--tessdata-dir` set to this
directory and `OMP_THREAD_LIMIT=1`. It NEVER downloads language data.
`tessdata_dir` must exist before the provider can be enabled.

## Required checksums

Run `python scripts/compute_model_checksums.py models/ocr/tesseract`
after placing language data files.

## License

Tesseract is Apache-2.0. Each `.traineddata` carries its own license —
verify before redistribution.
