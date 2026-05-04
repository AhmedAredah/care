# PII Policy

This document describes the PII detection, redaction, and review policy
for `care`.

## Entity types

The default detection chain is required to cover at least:

- `PERSON_NAME`
- `ADDRESS`
- `PHONE_NUMBER`
- `EMAIL`
- `DATE_OF_BIRTH`
- `DRIVER_LICENSE`
- `LICENSE_PLATE`
- `VIN`
- `INSURANCE_POLICY`
- `CASE_NUMBER`
- `REPORT_NUMBER`
- `SIGNATURE`
- `MEDICAL_INFO`
- `WITNESS_INFO`
- `VEHICLE_OWNER_INFO`
- `SSN` (when present)
- `VEHICLE_REGISTRATION` (when present)

## Recall over precision

False positives in this pipeline cost *useful narrative detail*; false
negatives can leak personal data into a public dataset. The chain is
therefore tuned for **recall**. Operators are free to tighten precision
for their jurisdiction, but the defaults must err on the side of
over-redaction.

## Provider chain (defaults)

The shipping default has a single provider:

1. `regex` — custom recognizers in `care/pii/recognizers/`.

Every other provider is registered but **disabled by default**.
Operators add them to `provider_chain` in `config.yaml` only after
following the activation policy in
[`docs/license-and-model-governance.md`](license-and-model-governance.md):

- `presidio` — Microsoft Presidio analyzer with local-only models (MIT).
- `piiranha` — third-party HF token-classification model.
  **Requires legal/license review before DOT deployment.** Loads only
  from local files.
- `roberta_ner` — RoBERTa-large general English NER (MIT). Supplements
  regex recognizers for free-text `PER` / `LOC` / `ORG` entities.
- `openai_privacy_filter` — OpenAI Privacy Filter (Apache-2.0). A
  bidirectional token-classification model trained for PII detection
  with eight labels (person, address, email, phone, date, URL,
  account number, secret). Requires `transformers>=5.6` from the
  `[ml]` extra. ~2.8 GB on disk.
- `mock_pii` — fixture provider for tests; never enabled outside CI.

## Redaction placeholders

Text redaction replaces detected PII with typed placeholders such as
`[PERSON_NAME]`, `[VIN]`, `[PHONE_NUMBER]`. The full list lives in
`care/redaction/policies.py`.

## Image redaction

Image redaction (diagram crops) uses pixel-level masking driven by
bounding boxes that come from a *trusted* source — native PDF text or
traditional OCR with confident bbox output. VLM-only text without
reliable bounding boxes is **never** sufficient.

## Unmapped PII

If a detector finds PII in text that cannot be mapped back to image
coordinates, the report is flagged `requires_review` and public export
is blocked until a human approves it.

## Logging

Logs are filtered through `care/core/logging.PIIRedactingFilter`,
which removes common PII shapes from log messages. Audit events never
contain raw PII; they reference entities by type and offset only.

## Public export

A public export contains only:

- `diagram.redacted.png`
- `narrative.redacted.txt`
- `narrative.redacted.json`
- `manifest.json`
- `qa.json`

It never contains the original PDF, original images, raw OCR or VLM
output, or any unredacted text.
