/* QA-flag glossary — maps the machine-readable codes the pipeline emits
   into short, plain-language explanations the reviewer can act on.

   Source of truth for the flag set: care/core/constants.py
   (QA_FLAGS / BLOCKING_QA_FLAGS / REVIEW_REQUIRED_QA_FLAGS). Keep this
   table aligned when new flags are added.

   Each entry has:
     title    — one-line headline shown in the report detail
     detail   — one-sentence explanation a non-engineer can act on
     severity — "block" | "review" | "info"
     advice   — what the reviewer or operator should do next
*/

(function (global) {
  "use strict";

  var BLOCKING = {
    TEMPLATE_UNKNOWN: 1,
    TEMPLATE_LOW_CONFIDENCE: 1,
    DIAGRAM_REGION_UNCERTAIN: 1,
    DIAGRAM_REGION_OUT_OF_BOUNDS: 1,
    DIAGRAM_CONTINUATION_UNCERTAIN: 1,
    REGION_AMBIGUOUS: 1,
    NARRATIVE_BOUNDARIES_UNCERTAIN: 1,
    NARRATIVE_ANCHORS_NOT_FOUND: 1,
    NARRATIVE_EMPTY: 1,
    NARRATIVE_CONTINUATION_ANCHOR_MISSING: 1,
    PII_UNMAPPED: 1,
    VLM_OUTPUT_CONFLICTS_WITH_OCR: 1,
  };

  /* Severity-only fallback for flags we haven't curated copy for yet —
     prevents the UI from rendering a raw enum. */
  function defaultEntry(code) {
    return {
      title: code.replace(/_/g, " ").toLowerCase(),
      detail:
        "The pipeline raised this QA flag. Open the manifest and qa.json " +
        "for the report to see provider-specific evidence.",
      severity: BLOCKING[code] ? "block" : "review",
      advice:
        "Review the redacted artifacts before approval; if the flag is " +
        "blocking, the QA gate has already refused export.",
    };
  }

  var GLOSSARY = {
    /* ---- template detection ---- */
    TEMPLATE_UNKNOWN: {
      title: "Unrecognized crash report form",
      detail:
        "The detector did not match any installed template. CARE will " +
        "not extract diagram or narrative regions from a form it doesn't " +
        "know — false redaction is unsafe.",
      severity: "block",
      advice:
        "Author a template for this state-and-version using the Template " +
        "builder, then re-run the report.",
    },
    TEMPLATE_LOW_CONFIDENCE: {
      title: "Low template-detection confidence",
      detail:
        "Identifier and form-number scores were below the configured " +
        "threshold, so the detector is uncertain which template applies.",
      severity: "block",
      advice:
        "Either tighten the template's identifiers, or restrict the run " +
        "to a known jurisdiction / template id.",
    },
    TEMPLATE_PAGE_COUNT_OUT_OF_RANGE: {
      title: "Page count outside the template's expected range",
      detail:
        "The report has more or fewer pages than this template normally " +
        "produces — possibly a different revision or a multi-form merge.",
      severity: "review",
      advice: "Verify the document is a single, complete crash report.",
    },

    /* ---- diagram extraction ---- */
    DIAGRAM_REGION_UNCERTAIN: {
      title: "Diagram region uncertain",
      detail:
        "The crash-diagram extractor's confidence was below threshold — " +
        "the cropped region may be wrong.",
      severity: "block",
      advice:
        "Inspect the redacted diagram. If the wrong area was cropped, " +
        "adjust the template's diagram region.",
    },
    DIAGRAM_REGION_OUT_OF_BOUNDS: {
      title: "Diagram region falls outside the page",
      detail:
        "The bbox declared by the template extends past the rendered " +
        "page bounds — likely a template-vs-form mismatch.",
      severity: "block",
      advice: "Re-author the template against a current sample of the form.",
    },
    DIAGRAM_PAGE_FALLBACK: {
      title: "Diagram page fallback used",
      detail:
        "The primary diagram page didn't match; the extractor fell back " +
        "to a candidate page. The crop is likely correct but worth a look.",
      severity: "review",
      advice: "Visually verify the diagram crop in the report detail.",
    },
    DIAGRAM_CANDIDATE_PAGE_USED: {
      title: "Diagram candidate page used",
      detail:
        "Diagram was extracted from a candidate page rather than the " +
        "primary page declared by the template.",
      severity: "info",
      advice: "Visual check recommended.",
    },
    DIAGRAM_CONTINUATION_UNCERTAIN: {
      title: "Diagram continuation uncertain",
      detail:
        "The diagram appears to continue onto another page but the " +
        "continuation heuristic was inconclusive.",
      severity: "block",
      advice:
        "Disable continuation in the template if the diagram is " +
        "single-page on this form, or tune the continuation rule.",
    },

    /* ---- narrative extraction ---- */
    NARRATIVE_BOUNDARIES_UNCERTAIN: {
      title: "Narrative boundaries uncertain",
      detail:
        "The narrative extractor could not confidently locate where the " +
        "officer's narrative paragraph starts and ends inside its region.",
      severity: "block",
      advice:
        "Check the narrative start / end anchors in the template. If the " +
        "form changed, update them.",
    },
    NARRATIVE_ANCHORS_NOT_FOUND: {
      title: "Narrative anchors not found",
      detail:
        "Neither the start nor end anchor was found on the page — most " +
        "likely the form revision changed.",
      severity: "block",
      advice: "Update the template anchors against a current sample.",
    },
    NARRATIVE_EMPTY: {
      title: "Narrative is empty",
      detail:
        "Anchors located the bounds but no text was extracted in between " +
        "— possibly an unsigned or blank form.",
      severity: "block",
      advice: "Confirm the report actually contains a written narrative.",
    },
    NARRATIVE_SPANS_PAGES: {
      title: "Narrative spans multiple pages",
      detail:
        "The narrative wraps onto a continuation page. The extractor " +
        "joined the spans; verify the result reads correctly.",
      severity: "info",
      advice: "Visual check recommended.",
    },
    NARRATIVE_CONTINUED: {
      title: "Narrative continued onto another page",
      detail:
        "The continuation rule joined narrative text from a continuation " +
        "page. Reading order is correct in the redacted output.",
      severity: "info",
      advice: "No action required.",
    },
    NARRATIVE_CONTINUATION_ANCHOR_MISSING: {
      title: "Narrative continuation cut off",
      detail:
        "A continuation page was used but the end anchor wasn't found — " +
        "the narrative may have been truncated.",
      severity: "block",
      advice: "Check whether the report has additional pages CARE didn't ingest.",
    },
    NARRATIVE_CONTINUATION_TRUNCATED: {
      title: "Narrative continuation truncated",
      detail:
        "Continuation hit the configured maximum-pages cap before the " +
        "end anchor was reached.",
      severity: "review",
      advice:
        "Raise <code>max_continuation_pages</code> in the template if " +
        "longer narratives are expected for this form.",
    },

    /* ---- anchors / regions ---- */
    REGION_AMBIGUOUS: {
      title: "Multiple plausible regions",
      detail:
        "More than one region candidate scored similarly — the chosen " +
        "one may not be correct.",
      severity: "block",
      advice:
        "Tighten the template's region bbox or add a discriminating " +
        "anchor.",
    },
    REGION_SHIFTED_PAGE: {
      title: "Region was shifted from declared page",
      detail:
        "The region was found on a nearby page rather than the page " +
        "declared by the template (forms drift between revisions).",
      severity: "review",
      advice: "Visual check recommended; consider widening candidate pages.",
    },
    TEMPLATE_ANCHORS_FUZZY_MATCHED: {
      title: "Template identifiers matched fuzzily",
      detail:
        "The detector matched on an approximate (fuzzy) version of the " +
        "identifier strings, usually due to OCR noise.",
      severity: "review",
      advice:
        "Confirm OCR quality and the chosen template are correct for " +
        "this form.",
    },
    NARRATIVE_ANCHORS_FUZZY_MATCHED: {
      title: "Narrative anchors matched fuzzily",
      detail:
        "Narrative start / end anchors matched approximately. Boundary " +
        "may be off by a word or two.",
      severity: "review",
      advice: "Visual check recommended.",
    },
    ANCHOR_LOW_CONFIDENCE: {
      title: "Anchor match below confidence floor",
      detail: "The anchor's match score was just barely above the floor.",
      severity: "review",
      advice:
        "Use the Template builder to add or refine identifiers for this " +
        "form.",
    },

    /* ---- OCR / VLM ---- */
    OCR_LOW_CONFIDENCE: {
      title: "OCR confidence below threshold",
      detail:
        "Mean OCR confidence on the page was low — text could be " +
        "misread, which can cascade into anchor and PII detection misses.",
      severity: "review",
      advice:
        "Re-scan the source at higher DPI or enable an additional OCR " +
        "engine in the chain.",
    },
    VLM_USED_FOR_EXTRACTION: {
      title: "VLM was used for extraction",
      detail:
        "A vision-language model contributed to the extracted text. " +
        "Generative models can hallucinate; manual review is required.",
      severity: "review",
      advice: "Read the redacted narrative against the diagram visually.",
    },
    VLM_USED_FOR_TEMPLATE_DETECTION: {
      title: "VLM contributed to template detection",
      detail:
        "A vision-language model helped pick the template. Manual " +
        "verification recommended on first uses of this form.",
      severity: "review",
      advice: "Confirm the chosen template id matches the form.",
    },
    VLM_OUTPUT_CONFLICTS_WITH_OCR: {
      title: "VLM disagreed with OCR",
      detail:
        "The vision-language model and traditional OCR returned " +
        "conflicting text for the same region. CARE will not export " +
        "until a human resolves the conflict.",
      severity: "block",
      advice:
        "Inspect both readings in the manifest; correct OCR by re-scanning " +
        "or update the OCR provider chain.",
    },
    VLM_OUTPUT_HAS_NO_BBOXES: {
      title: "VLM output has no bounding boxes",
      detail:
        "The VLM produced text but no pixel coordinates. CARE never " +
        "drives image redaction from VLM-only text — the diagram was " +
        "redacted from OCR/native text only.",
      severity: "review",
      advice:
        "Check that diagram redaction looks correct; consider disabling " +
        "the VLM if it consistently omits bboxes.",
    },
    VLM_PII_NOT_MAPPABLE_TO_IMAGE: {
      title: "VLM-detected PII can't be mapped to pixels",
      detail:
        "VLM flagged a PII span without coordinates, so the image " +
        "redactor cannot mask it on the diagram crop.",
      severity: "block",
      advice:
        "Re-run with a PII detector that produces image coordinates, or " +
        "disable the VLM PII path.",
    },
    VLM_GENERATIVE_OUTPUT_REQUIRES_REVIEW: {
      title: "VLM generative output — review required",
      detail:
        "Output came from a generative model, which can hallucinate " +
        "details that aren't on the page.",
      severity: "review",
      advice: "Compare the redacted narrative against the original visually.",
    },
    VLM_MODEL_NOT_BENCHMARKED_FOR_THIS_TEMPLATE: {
      title: "VLM not benchmarked for this template",
      detail:
        "This VLM has never been evaluated against this template — " +
        "behavior is unknown.",
      severity: "review",
      advice: "Run the evaluation harness on a synthetic batch first.",
    },
    DIAGRAM_VLM_DISAGREES: {
      title: "VLM disagrees with diagram extraction",
      detail:
        "The VLM's interpretation of the diagram region disagrees with " +
        "the extractor's crop.",
      severity: "review",
      advice: "Visually verify the redacted diagram matches the source.",
    },

    /* ---- PII ---- */
    PII_UNMAPPED: {
      title: "PII could not be mapped to image coordinates",
      detail:
        "At least one detected PII span has no pixel bbox, so the image " +
        "redactor cannot mask it on the diagram. Releasing this report " +
        "would leak PII.",
      severity: "block",
      advice:
        "Use a PII detector that produces image coordinates (Presidio + " +
        "OCR span join), or disable the providers that produced unmapped " +
        "spans for this template.",
    },

    /* ---- offline guard ---- */
    OFFLINE_GUARD_TRIGGERED: {
      title: "Offline guard intercepted a network call",
      detail:
        "Some component tried to open an outbound connection while " +
        "offline mode was on. The call was blocked.",
      severity: "review",
      advice:
        "Check the audit log for the calling provider — it likely needs " +
        "a local model directory configured.",
    },

    /* ---- LayoutLM authoring helper ---- */
    LAYOUTLM_PLUGIN_USED: {
      title: "LayoutLM region suggester was used",
      detail:
        "LayoutLM helped propose regions during template authoring. Any " +
        "regions it suggested must be visually confirmed.",
      severity: "review",
      advice: "Re-open the template builder and verify each accepted region.",
    },
    LAYOUTLM_REGION_SUGGESTION: {
      title: "Region came from a LayoutLM suggestion",
      detail: "A region used here originated as an AI suggestion.",
      severity: "review",
      advice: "Visual check recommended.",
    },
    LAYOUTLM_FALLBACK_USED: {
      title: "Heuristic fallback used (no LayoutLM model)",
      detail:
        "LayoutLM model wasn't available; an offline heuristic produced " +
        "the suggestion instead.",
      severity: "review",
      advice: "Visual check recommended.",
    },
    LAYOUTLM_CONFLICT_WITH_TEMPLATE: {
      title: "LayoutLM disagrees with the template",
      detail:
        "LayoutLM proposed a region that conflicts with what the " +
        "template declared.",
      severity: "review",
      advice: "Reconcile manually in the template builder.",
    },
    LAYOUTLM_REQUIRES_REVIEW: {
      title: "LayoutLM output — review required",
      detail: "Standing review-required flag set whenever LayoutLM contributes.",
      severity: "review",
      advice: "No action beyond visual review.",
    },
    LAYOUTLM_LICENSE_REVIEW_REQUIRED: {
      title: "LayoutLM model carries license-review obligations",
      detail:
        "The LayoutLM weights have a non-permissive license that DOTs " +
        "should clear with counsel before public release.",
      severity: "review",
      advice: "See license manifest in the report's manifest.json.",
    },

    /* ---- LLM/VLM service usage (Phase 12+) ---- */
    LLM_PROVIDER_USED: {
      title: "LLM provider was used",
      detail: "A large-language-model provider was invoked.",
      severity: "review",
      advice: "Visual check recommended.",
    },
    LLM_REGION_SUGGESTION: {
      title: "Region came from an LLM suggestion",
      detail: "Visual check recommended.",
      severity: "review",
      advice: "Confirm against the source.",
    },
    LLM_ANCHOR_SUGGESTION: {
      title: "Anchor came from an LLM suggestion",
      detail: "Visual check recommended.",
      severity: "review",
      advice: "Confirm against the source.",
    },
    LLM_QA_SECOND_OPINION: {
      title: "LLM QA second opinion attached",
      detail: "An LLM was asked for a second opinion on this report.",
      severity: "info",
      advice: "Read the second opinion in the manifest.",
    },
    LLM_EXTERNAL_PROVIDER_USED: {
      title: "External LLM provider used",
      detail:
        "A non-local LLM provider was used — air-gapped operators should " +
        "verify this matches policy.",
      severity: "review",
      advice: "Disable external providers in the LLM section if unintended.",
    },
    LLM_REQUIRES_REVIEW: {
      title: "LLM output — review required",
      detail: "Standing review-required flag whenever an LLM contributes.",
      severity: "review",
      advice: "No action beyond visual review.",
    },
    LLM_OUTPUT_UNMAPPED: {
      title: "LLM output couldn't be mapped to source",
      detail: "LLM produced output without source spans / coordinates.",
      severity: "review",
      advice: "Visual check recommended.",
    },
    LLM_CONFLICT_WITH_TEMPLATE: {
      title: "LLM disagrees with the template",
      detail: "LLM output conflicts with what the template declared.",
      severity: "review",
      advice: "Reconcile manually.",
    },
  };

  /* Look up a flag, returning a curated entry or a synthesized fallback. */
  function explain(code) {
    return GLOSSARY[code] || defaultEntry(code);
  }

  /* Return the most-blocking flag from a list, falling back to the
     highest-severity if none block. */
  function topConcern(flags) {
    if (!flags || !flags.length) return null;
    var blocked = null;
    var review = null;
    for (var i = 0; i < flags.length; i++) {
      var f = flags[i];
      var entry = explain(f);
      if (entry.severity === "block" && !blocked) blocked = f;
      else if (entry.severity === "review" && !review) review = f;
    }
    return blocked || review || flags[0];
  }

  function isBlocking(code) { return !!BLOCKING[code]; }

  global.OCEQAGlossary = {
    explain: explain,
    topConcern: topConcern,
    isBlocking: isBlocking,
  };
})(window);
