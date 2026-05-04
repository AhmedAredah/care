"""Template detection.

If no template scores at or above the configured confidence threshold,
the detector returns an UNKNOWN match with the `TEMPLATE_UNKNOWN` and
`TEMPLATE_LOW_CONFIDENCE` flags set. Unknown templates must NEVER be
auto-exported (GOVERNANCE.md §Fail-Closed Rules).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.constants import TEMPLATE_UNKNOWN_ID
from ..document_ir.models import DocumentIR
from .registry import TemplateRegistry
from .scoring import TemplateScoreEvidence, score_template


@dataclass
class TemplateMatchEvidence:
    anchor_text_found: list[str] = field(default_factory=list)
    anchor_text_missing: list[str] = field(default_factory=list)
    form_number_match: str | None = None
    page_count: int = 0
    page_count_in_range: bool = True
    region_bboxes_plausible: bool = True
    candidate_scores: dict[str, float] = field(default_factory=dict)
    anchor_text_fuzzy_matched: list[str] = field(default_factory=list)


@dataclass
class TemplateMatch:
    template_id: str
    version: str | None
    confidence: float
    evidence: TemplateMatchEvidence
    warnings: list[str] = field(default_factory=list)
    requires_review: bool = False


def _evidence_from(score_ev: TemplateScoreEvidence, candidate_scores: dict[str, float]) -> TemplateMatchEvidence:
    return TemplateMatchEvidence(
        anchor_text_found=list(score_ev.anchor_text_found),
        anchor_text_missing=list(score_ev.anchor_text_missing),
        form_number_match=score_ev.form_number_match,
        page_count=score_ev.page_count,
        page_count_in_range=score_ev.page_count_in_range,
        region_bboxes_plausible=score_ev.region_bboxes_plausible,
        candidate_scores=dict(candidate_scores),
        anchor_text_fuzzy_matched=list(score_ev.anchor_text_fuzzy_matched),
    )


def detect_template(
    document_ir: DocumentIR,
    registry: TemplateRegistry,
    *,
    confidence_threshold: float = 0.85,
    ocr_confidence_average: float | None = None,
) -> TemplateMatch:
    """Score every registered template and return the highest-confidence match.

    Returns a TemplateMatch with `template_id == "UNKNOWN"` if no template
    is registered or if the best score is below `confidence_threshold`.
    """
    candidates = registry.all()
    candidate_scores: dict[str, float] = {}

    if not candidates:
        return TemplateMatch(
            template_id=TEMPLATE_UNKNOWN_ID,
            version=None,
            confidence=0.0,
            evidence=TemplateMatchEvidence(page_count=len(document_ir.pages)),
            warnings=["TEMPLATE_UNKNOWN", "TEMPLATE_LOW_CONFIDENCE"],
            requires_review=True,
        )

    best = None
    best_score = None
    for template in candidates:
        score = score_template(
            template,
            document_ir,
            ocr_confidence_average=ocr_confidence_average,
        )
        candidate_scores[template.template_id] = score.confidence
        if best_score is None or score.confidence > best_score.confidence:
            best = template
            best_score = score

    assert best is not None and best_score is not None  # candidates non-empty

    if best_score.confidence < confidence_threshold:
        warnings = ["TEMPLATE_UNKNOWN", "TEMPLATE_LOW_CONFIDENCE"]
        if not best_score.evidence.page_count_in_range:
            warnings.append("TEMPLATE_PAGE_COUNT_OUT_OF_RANGE")
        return TemplateMatch(
            template_id=TEMPLATE_UNKNOWN_ID,
            version=None,
            confidence=best_score.confidence,
            evidence=_evidence_from(best_score.evidence, candidate_scores),
            warnings=warnings,
            requires_review=True,
        )

    warnings: list[str] = []
    if best_score.evidence.anchor_text_missing:
        warnings.append("TEMPLATE_ANCHORS_PARTIALLY_MISSING")
    if best_score.evidence.anchor_text_fuzzy_matched:
        warnings.append("TEMPLATE_ANCHORS_FUZZY_MATCHED")
    if not best_score.evidence.region_bboxes_plausible:
        warnings.append("TEMPLATE_REGION_BBOX_INVALID")

    return TemplateMatch(
        template_id=best.template_id,
        version=best.version,
        confidence=best_score.confidence,
        evidence=_evidence_from(best_score.evidence, candidate_scores),
        warnings=warnings,
        requires_review=False,
    )
