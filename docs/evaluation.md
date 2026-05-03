# Evaluation

This document describes how to measure the system's behaviour on
synthetic fixtures. Real DOT data must never enter the evaluation
pipeline.

## Synthetic fixtures

Every fixture in `tests/_fixtures.py` is generated at test time with
`fpdf2` + Pillow:

- `make_synthetic_image` — labelled raster
- `make_digital_pdf` — PDF with a real text layer
- `make_image_only_pdf` — rasterised PDF with no text layer
- `make_example_template_pdf` — matches `example_state_crash_v1`
- `make_unknown_template_pdf` — matches no template

Add new fixtures by composing these helpers; do not commit binary
PDFs/images to the repo.

## Metrics emitted by the pipeline

For every report, the manifest records:

- `template_confidence`, `diagram_confidence`, `narrative_confidence`
- OCR provider used + version
- VLM warning codes
- PII entity count, unmapped count
- QA flags + blocking reasons

A simple eval harness can compare these values against fixture-level
expectations and produce a confusion matrix. Because every fixture is
synthesized at runtime, ground truth is the data passed into the
fixture helper.

## Recommended categories

| Category | Fixture | Expected outcome |
|---|---|---|
| Happy path image | `make_synthetic_image` + `mock_tokens=PII_TOKENS` | `qa.export_decision == "ALLOW"` |
| Happy path PDF | `make_example_template_pdf` | `ALLOW` |
| Unknown template | `make_unknown_template_pdf` | `BLOCK`, `TEMPLATE_UNKNOWN` |
| VLM no-bboxes | `mock_vlm` mock_mode `no_bboxes` | warning `VLM_OUTPUT_HAS_NO_BBOXES`, no AlternativeSource attached |
| VLM conflict | `mock_vlm` mock_mode `conflict_with_ocr` | `BLOCK`, `VLM_OUTPUT_CONFLICTS_WITH_OCR` |
| Unmapped PII | `mock_ocr` without bboxes | `BLOCK`, `PII_UNMAPPED` |

## Recall vs. precision targets

The PII layer prioritises recall over precision (better to over-redact
than to leak). The default regex chain is tuned to detect:

- VINs (17-char alnum)
- US plates (`[A-Z0-9]{5,8}`)
- US driver licences (jurisdiction-prefixed)
- Phones (3-3-4 digits with separators)
- Emails (`local@host.tld`)
- Addresses (`<num> <street>`)
- DOBs (`YYYY-MM-DD` and US formats)
- Report / case / insurance numbers (label-prefixed)
- Person names (capitalised bigram heuristic)
- Signature / medical info (label-prefixed)

False positives are acceptable; missing a real entity is not. The
test suite asserts recall on fixtures that include canonical shapes
of every entity type.

## Adding a new evaluation case

1. Build a synthetic fixture in `tests/_fixtures.py`.
2. Add an integration test under `tests/integration/test_pipeline_phaseN.py`
   that asserts the QA outcome you expect.
3. If you're adding a new entity type, also add a unit test under
   `tests/unit/test_pii_recognizers.py` asserting both shape match
   AND case-sensitivity behaviour (the value group is case-sensitive
   for label-prefixed recognizers).
