"""Project-wide constants."""
from __future__ import annotations

APP_NAME = "care"
APP_VERSION = "0.1.0"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7860

SUPPORTED_FILE_EXTENSIONS: frozenset[str] = frozenset({
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
})

# QA flag vocabulary used by the reconciliation and review stages.
# Phase 1 lists the full set so downstream code (Phase 3+) has a stable
# vocabulary to reference.
QA_FLAGS: frozenset[str] = frozenset({
    "VLM_USED_FOR_EXTRACTION",
    "VLM_USED_FOR_TEMPLATE_DETECTION",
    "VLM_OUTPUT_CONFLICTS_WITH_OCR",
    "VLM_OUTPUT_HAS_NO_BBOXES",
    "VLM_PII_NOT_MAPPABLE_TO_IMAGE",
    "VLM_GENERATIVE_OUTPUT_REQUIRES_REVIEW",
    "VLM_MODEL_NOT_BENCHMARKED_FOR_THIS_TEMPLATE",
    "TEMPLATE_UNKNOWN",
    "TEMPLATE_LOW_CONFIDENCE",
    "TEMPLATE_PAGE_COUNT_OUT_OF_RANGE",
    "DIAGRAM_REGION_UNCERTAIN",
    "DIAGRAM_REGION_OUT_OF_BOUNDS",
    # Phase 7+ multi-page region handling.
    "DIAGRAM_PAGE_FALLBACK",
    "DIAGRAM_CANDIDATE_PAGE_USED",
    "DIAGRAM_CONTINUATION_UNCERTAIN",
    "REGION_AMBIGUOUS",
    "REGION_SHIFTED_PAGE",
    "NARRATIVE_BOUNDARIES_UNCERTAIN",
    "NARRATIVE_ANCHORS_NOT_FOUND",
    "NARRATIVE_EMPTY",
    "NARRATIVE_SPANS_PAGES",
    "NARRATIVE_CONTINUED",
    "NARRATIVE_CONTINUATION_ANCHOR_MISSING",
    "NARRATIVE_CONTINUATION_TRUNCATED",
    "OCR_LOW_CONFIDENCE",
    "PII_UNMAPPED",
    "OFFLINE_GUARD_TRIGGERED",
    # Phase 9 — extraction robustness (fuzzy anchors + VLM second-opinion).
    "TEMPLATE_ANCHORS_FUZZY_MATCHED",
    "NARRATIVE_ANCHORS_FUZZY_MATCHED",
    "ANCHOR_LOW_CONFIDENCE",
    "DIAGRAM_VLM_DISAGREES",
    # Phase 10 — optional LayoutLM plugin (suggestion-only, never drives
    # export, never drives PII redaction, always review-gated).
    "LAYOUTLM_PLUGIN_USED",
    "LAYOUTLM_REGION_SUGGESTION",
    "LAYOUTLM_FALLBACK_USED",
    "LAYOUTLM_CONFLICT_WITH_TEMPLATE",
    "LAYOUTLM_REQUIRES_REVIEW",
    "LAYOUTLM_LICENSE_REVIEW_REQUIRED",
    # Phase 12 — vendor-agnostic LLM/VLM plugin layer (cloud + local).
    # Suggestion-only, never drives export/redaction, always review-gated.
    "LLM_PROVIDER_USED",
    "LLM_REGION_SUGGESTION",
    "LLM_ANCHOR_SUGGESTION",
    "LLM_QA_SECOND_OPINION",
    "LLM_EXTERNAL_PROVIDER_USED",
    "LLM_REQUIRES_REVIEW",
    "LLM_OUTPUT_UNMAPPED",
    "LLM_CONFLICT_WITH_TEMPLATE",
})

# QA flags that ALWAYS block public export (used by qa_flags.build_qa_report).
BLOCKING_QA_FLAGS: frozenset[str] = frozenset({
    "TEMPLATE_UNKNOWN",
    "TEMPLATE_LOW_CONFIDENCE",
    "DIAGRAM_REGION_UNCERTAIN",
    "DIAGRAM_REGION_OUT_OF_BOUNDS",
    "DIAGRAM_CONTINUATION_UNCERTAIN",
    "REGION_AMBIGUOUS",
    "NARRATIVE_BOUNDARIES_UNCERTAIN",
    "NARRATIVE_ANCHORS_NOT_FOUND",
    "NARRATIVE_EMPTY",
    "NARRATIVE_CONTINUATION_ANCHOR_MISSING",
    "PII_UNMAPPED",
    "VLM_OUTPUT_CONFLICTS_WITH_OCR",
})

# QA flags that force ``requires_human_review=True`` without blocking
# public export by themselves. Used for informational signals that
# nonetheless need a human in the loop (e.g. LayoutLM suggestions —
# never drive export, but must always be reviewed).
REVIEW_REQUIRED_QA_FLAGS: frozenset[str] = frozenset({
    "LAYOUTLM_PLUGIN_USED",
    "LAYOUTLM_REGION_SUGGESTION",
    "LAYOUTLM_FALLBACK_USED",
    "LAYOUTLM_CONFLICT_WITH_TEMPLATE",
    "LAYOUTLM_REQUIRES_REVIEW",
    "LAYOUTLM_LICENSE_REVIEW_REQUIRED",
    # Phase 12 — every LLM/VLM provider use forces human review.
    "LLM_PROVIDER_USED",
    "LLM_REGION_SUGGESTION",
    "LLM_ANCHOR_SUGGESTION",
    "LLM_QA_SECOND_OPINION",
    "LLM_EXTERNAL_PROVIDER_USED",
    "LLM_REQUIRES_REVIEW",
    "LLM_OUTPUT_UNMAPPED",
    "LLM_CONFLICT_WITH_TEMPLATE",
})

TEMPLATE_UNKNOWN_ID = "UNKNOWN"

HF_OFFLINE_ENV: dict[str, str] = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
}
