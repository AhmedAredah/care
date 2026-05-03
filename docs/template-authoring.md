# Template authoring

A *template* tells the pipeline how to recognise one specific crash
report layout and where to find its diagram and narrative regions.
Templates live under `templates/<jurisdiction>/<id>.yaml`.

## Schema

```yaml
template_id: example_state_crash_v1
jurisdiction: example_state
agency: example_state_dot
version: "1.0"
description: "Example synthetic state crash report (DO NOT USE on real reports)."

signature:
  anchor_text:
    - "Example Crash Report"
    - "Form: EX-CR-"
    - "Diagram"
    - "Narrative"
  form_number_regex: "EX-CR-\\d{1,8}"

layout:
  page_count_min: 1
  page_count_max: 4

regions:
  diagram:
    page: 0
    bbox_norm: [0.05, 0.10, 0.95, 0.50]
    anchor_start: "Diagram"
  narrative:
    page: 0
    bbox_norm: [0.05, 0.55, 0.95, 0.95]
    anchor_start: "Narrative"
    anchor_end: "Officer"
```

`bbox_norm` is `[x0, y0, x1, y1]` in normalised page coordinates
(0..1, top-left origin). Every value must satisfy `0 <= x0 < x1 <= 1`.

## Detection scoring

`care/templates/detector.py::detect_template` aggregates these
signals into a confidence score:

- **anchor coverage** — fraction of `signature.anchor_text` substrings
  that appear (case-insensitive) anywhere in the document text.
- **form-number match** — boolean from `signature.form_number_regex`.
- **page count in range** — boolean.
- **layout plausibility** — every declared region's `bbox_norm`
  passes the schema validator.

Templates that score below `cfg.template_detection.confidence_threshold`
(default 0.85) are flagged `TEMPLATE_LOW_CONFIDENCE` and the QA gate
blocks export. The reserved `UNKNOWN` template id is returned when no
candidate clears the threshold.

## Authoring workflow

1. Pull a synthetic example of the layout you want to support — never
   a real crash report.
2. Identify three to five short anchor strings that ALWAYS appear on
   the form (form name, section headings, fixed labels). Anchor
   strings are matched case-insensitively but exactly otherwise — do
   not include OCR-prone characters like long ligatures or accented
   letters.
3. If the form has a form-number on every page, add a regex to
   `form_number_regex`. Keep it specific (anchor it on a literal
   prefix) so it doesn't match unrelated digits.
4. Measure the diagram and narrative regions on a rendered version of
   the form (DPI 200 is a reasonable default). Convert pixel bounds
   to normalised coordinates: `x_norm = x_px / page_width_px`. Leave a
   small margin so OCR drift doesn't push glyphs out of the bbox.
5. Validate locally:

   ```
   python -m care.cli validate-template templates/<jurisdiction>/<id>.yaml
   ```

6. Add an integration test that runs the pipeline against a synthetic
   PDF carrying the new layout. The test should assert
   `qa.export_decision == "ALLOW"` on the happy path and the expected
   QA flags on near-misses.

## Things to avoid

- **Real DOT data.** All fixtures must be clearly synthetic.
- **Free-text anchors.** Anchors should be deterministic strings, not
  paragraph fragments that vary across reports.
- **Tight bboxes.** Leave margin for OCR jitter and font kerning.
- **Optional anchors.** Do not list anchor strings that only appear
  on some forms — they will drag the score down.

## LayoutLM-assisted authoring (Phase 10, optional)

When the operator enables the LayoutLM plugin (disabled by default),
the template builder may surface region suggestions ("the diagram
probably lives in this bbox on this page"). The workflow is:

1. The operator clicks **Suggest regions** in the builder. The plugin
   runs against the current page's words + bboxes.
2. Suggestions appear as dashed proposals on the canvas. They do
   nothing automatically.
3. The operator clicks **Accept** to convert a suggestion into the
   template's `diagram` or `narrative` region. The resulting template
   is identical to one drawn by hand.
4. Rejected suggestions are discarded; the report (when run later)
   never inherits "LayoutLM said so" provenance.

LayoutLM-assisted authoring is a productivity tool, not a license to
ship un-reviewed templates. Every accepted suggestion still passes
through `validate-template` and the same scoring as a hand-drawn
template. If you skip the **Accept** step, the suggestion does not
travel with the template — it lives only on the operator's screen.
