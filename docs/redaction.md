# Redaction

This document explains how `care` rewrites narrative
text and overpaints image regions before public export.

## Detection → mapping → redaction

1. **Detection.** The PII provider chain (`regex` by default; optional
   `presidio`, `piiranha`, and `roberta_ner`) emits `PIIEntity`
   records carrying the entity type, source-text offsets, and a
   confidence.
2. **Mapping.** `redaction/bbox_mapper.py` walks each page's words
   and pairs entity-text spans with the corresponding word bboxes.
   Entities whose source span has no bbox stay unmapped, which the
   QA gate detects as `PII_UNMAPPED` and treats as a blocking
   condition.
3. **Redaction.**
   - `redaction/text_redactor.py` rewrites narrative text right-to-left,
     replacing matched spans with `[ENTITY_TYPE]` placeholders so
     downstream offsets remain meaningful.
   - `redaction/image_redactor.py` opens the page image, expands every
     mapped bbox by a configurable margin, and paints solid black
     rectangles. The cropped diagram is then taken from the redacted
     page, never the original.

The exporter (`export/exporter.py`) consumes the redacted text and
redacted image crop. Originals never leave `work_dir`.

## Placeholder vocabulary

```
[PERSON_NAME]   [ADDRESS]   [PHONE_NUMBER]   [EMAIL]   [DATE_OF_BIRTH]
[DRIVER_LICENSE]   [LICENSE_PLATE]   [VIN]   [INSURANCE_POLICY]
[CASE_NUMBER]   [REPORT_NUMBER]   [SIGNATURE]   [MEDICAL_INFO]
[WITNESS_INFO]   [VEHICLE_OWNER_INFO]   [SSN]   [VEHICLE_REGISTRATION]
[FULL_FACE_IMAGE]
```

Placeholders are stable across versions; downstream tooling can rely
on them as well-known sentinels.

## Audit log

`narrative.redacted.json::entities_redacted[]` records, for every
applied redaction:

- `entity_type`
- `provider`
- `start_offset`, `end_offset` (in the original narrative text)
- `bbox` (only when mapped)

It does **not** record the raw matched text. The corresponding
`manifest.json` entries record the PII chain used and whether image
redaction depended on bboxes from any non-base provider (always
`false` in the default chain).

## Fail-closed cases

- Any PII entity that cannot be mapped to image coordinates →
  `PII_UNMAPPED` → export blocked.
- Any narrative anchor not found → narrative confidence below
  threshold → export blocked.
- Any VLM/OCR conflict at a redacted span → `VLM_OUTPUT_CONFLICTS_WITH_OCR`
  → export blocked.

The pipeline never falls back to "redact whatever we have." If we
can't produce a provably safe artifact, the report goes to human
review.
