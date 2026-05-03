"""Template scoring helpers.

Phase 3 signals:
- anchor_text coverage (fraction of declared anchors found)
- form_number_regex match (boolean)
- page count within `layout.page_count_min/max` (precondition: outside range → score 0)
- region bbox plausibility (sanity)

Phase 9 hardens anchor matching: anchors are normalized (whitespace,
casing, NFC, outer punctuation) before comparison, and a fuzzy fallback
catches single-character OCR errors. Fuzzy matches contribute to
coverage at a 0.8 weight so a near-identical template that still
matches every anchor exactly outscores a sibling that only matched
fuzzily.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..document_ir.models import DocumentIR
from ..extraction.anchor_match import (
    DEFAULT_FUZZY_THRESHOLD,
    AnchorCoverage,
    score_anchor_coverage,
)
from .schemas import TemplateSchema


@dataclass(frozen=True)
class TemplateScoreEvidence:
    anchor_text_found: tuple[str, ...]
    anchor_text_missing: tuple[str, ...]
    form_number_match: Optional[str]
    page_count: int
    page_count_in_range: bool
    region_bboxes_plausible: bool
    anchor_text_fuzzy_matched: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplateScore:
    template_id: str
    version: str
    confidence: float
    evidence: TemplateScoreEvidence


def _document_text(doc: DocumentIR) -> str:
    """Concatenate every page's word tokens into a single search string."""
    return " ".join(
        " ".join(word.text for word in page.words) for page in doc.pages
    )


def score_template(
    template: TemplateSchema,
    document_ir: DocumentIR,
    *,
    ocr_confidence_average: Optional[float] = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    allow_fuzzy_anchors: bool = True,
) -> TemplateScore:
    """Return a 0..1 confidence score for `template` against `document_ir`.

    Page-count is a hard precondition: outside the declared range → 0.
    Anchor coverage is the dominant soft signal (now normalized + fuzzy);
    form-number regex (when declared) is a secondary signal. OCR
    confidence below 0.5 dampens the final score by 20%.
    """
    page_count = len(document_ir.pages)
    pc_min = template.layout.page_count_min
    pc_max = template.layout.page_count_max
    in_range = pc_min <= page_count <= pc_max

    anchors = list(template.signature.anchor_text or [])
    haystack = _document_text(document_ir)
    coverage: AnchorCoverage = score_anchor_coverage(
        anchors,
        haystack,
        fuzzy_threshold=fuzzy_threshold,
        allow_fuzzy=allow_fuzzy_anchors,
    )
    anchor_score = coverage.coverage_score

    form_score: Optional[float] = None
    form_match: Optional[str] = None
    if template.signature.form_number_regex:
        m = re.search(
            template.signature.form_number_regex, haystack, re.IGNORECASE
        )
        if m:
            form_match = m.group(0)
            form_score = 1.0
        else:
            form_score = 0.0

    region_plausible = True
    for region in template.regions.values():
        if region.bbox_norm is not None:
            x0, y0, x1, y1 = region.bbox_norm
            if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
                region_plausible = False
                break

    if not in_range:
        confidence = 0.0
    else:
        if form_score is not None and anchors:
            confidence = 0.7 * anchor_score + 0.3 * form_score
        elif anchors:
            confidence = anchor_score
        elif form_score is not None:
            confidence = form_score
        else:
            confidence = 0.0

        if ocr_confidence_average is not None and ocr_confidence_average < 0.5:
            confidence *= 0.8

        if not region_plausible:
            confidence *= 0.5

    return TemplateScore(
        template_id=template.template_id,
        version=template.version,
        confidence=round(confidence, 4),
        evidence=TemplateScoreEvidence(
            anchor_text_found=coverage.found_exact + coverage.found_fuzzy,
            anchor_text_missing=coverage.missing,
            form_number_match=form_match,
            page_count=page_count,
            page_count_in_range=in_range,
            region_bboxes_plausible=region_plausible,
            anchor_text_fuzzy_matched=coverage.found_fuzzy,
        ),
    )
