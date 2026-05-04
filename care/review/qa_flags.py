"""QA gate / fail-closed logic.

Every blocking reason here flips `export_decision` to `BLOCK` and forces
`requires_human_review = True`. The Phase 4 exporter MUST refuse to
write any public artifact when `qa.export_blocked` is True.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..core.constants import BLOCKING_QA_FLAGS, TEMPLATE_UNKNOWN_ID
from ..document_ir.models import Warning as IRWarning
from ..extraction.diagram_extractor import DiagramExtraction
from ..extraction.narrative_extractor import NarrativeExtraction
from ..pii.entities import PIIEntity
from ..templates.detector import TemplateMatch


@dataclass
class QAReport:
    export_decision: str  # "ALLOW" | "BLOCK"
    export_blocked: bool
    blocking_reasons: list[str] = field(default_factory=list)
    qa_flags: list[str] = field(default_factory=list)
    requires_human_review: bool = False
    template_confidence: float | None = None
    diagram_confidence: float | None = None
    narrative_confidence: float | None = None
    pii_entity_count: int = 0
    pii_unmapped_count: int = 0


def build_qa_report(
    template_match: TemplateMatch,
    diagram: DiagramExtraction | None,
    narrative: NarrativeExtraction | None,
    *,
    pii_entities_pages: Iterable[PIIEntity] | None = None,
    vlm_warnings: Iterable[IRWarning] | None = None,
    template_confidence_threshold: float = 0.85,
) -> QAReport:
    blocking_reasons: list[str] = []
    qa_flags: list[str] = []
    requires_review = False

    # ---- Template-level gates -------------------------------------------

    if template_match.template_id == TEMPLATE_UNKNOWN_ID:
        qa_flags.append("TEMPLATE_UNKNOWN")
        blocking_reasons.append(
            "Template is UNKNOWN; GOVERNANCE.md requires human review for unknown templates."
        )
        requires_review = True

    if template_match.confidence < template_confidence_threshold:
        qa_flags.append("TEMPLATE_LOW_CONFIDENCE")
        if template_match.template_id != TEMPLATE_UNKNOWN_ID:
            blocking_reasons.append(
                f"Template confidence {template_match.confidence:.2f} below "
                f"threshold {template_confidence_threshold:.2f}."
            )
        requires_review = True

    if not template_match.evidence.page_count_in_range:
        qa_flags.append("TEMPLATE_PAGE_COUNT_OUT_OF_RANGE")

    # ---- Diagram / narrative gates --------------------------------------

    if template_match.template_id != TEMPLATE_UNKNOWN_ID:
        if diagram is None:
            qa_flags.append("DIAGRAM_REGION_UNCERTAIN")
            blocking_reasons.append(
                "Template declares no diagram region or extraction returned None."
            )
            requires_review = True
        else:
            qa_flags.extend(diagram.warnings)
            if diagram.requires_review:
                blocking_reasons.append(
                    f"Diagram extraction requires review (confidence {diagram.confidence:.2f})."
                )
                requires_review = True

        if narrative is None:
            qa_flags.append("NARRATIVE_BOUNDARIES_UNCERTAIN")
            blocking_reasons.append(
                "Template declares no narrative region or extraction returned None."
            )
            requires_review = True
        else:
            qa_flags.extend(narrative.warnings)
            if narrative.requires_review:
                blocking_reasons.append(
                    f"Narrative extraction requires review (confidence {narrative.confidence:.2f})."
                )
                requires_review = True

    # ---- PII gates (Phase 4) --------------------------------------------

    pii_entity_count = 0
    pii_unmapped_count = 0
    if pii_entities_pages is not None:
        pii_entities_list = list(pii_entities_pages)
        pii_entity_count = len(pii_entities_list)
        unmapped = [
            e
            for e in pii_entities_list
            if not e.can_map_to_image_coordinates or e.bbox is None
        ]
        pii_unmapped_count = len(unmapped)
        if unmapped:
            qa_flags.append("PII_UNMAPPED")
            blocking_reasons.append(
                f"{len(unmapped)} PII entit"
                f"{'y' if len(unmapped) == 1 else 'ies'} "
                f"could not be mapped to image coordinates; redaction is unsafe."
            )
            requires_review = True

    # ---- VLM / reconciliation gates (Phase 5) ---------------------------

    if vlm_warnings is not None:
        for warning in vlm_warnings:
            qa_flags.append(warning.code)
            if warning.code == "VLM_OUTPUT_CONFLICTS_WITH_OCR":
                blocking_reasons.append(
                    "VLM output disagrees with OCR/native text — review required."
                )
                requires_review = True
            elif warning.code == "VLM_GENERATIVE_OUTPUT_REQUIRES_REVIEW":
                requires_review = True

    # Phase 7+ multi-page region flags: any blocking flag in the
    # consolidated set forces fail-closed even if no extractor wrote
    # a blocking_reason directly.
    for flag in qa_flags:
        if flag in BLOCKING_QA_FLAGS and not any(flag in r for r in blocking_reasons):
            blocking_reasons.append(f"{flag} requires review")
            requires_review = True

    # Phase 10+ review-required flags: do NOT block export, but DO
    # force human review. Used by the LayoutLM plugin so any
    # suggestion that survives into the report must be eyeballed
    # before approval.
    from ..core.constants import REVIEW_REQUIRED_QA_FLAGS

    for flag in qa_flags:
        if flag in REVIEW_REQUIRED_QA_FLAGS:
            requires_review = True
            break

    export_blocked = bool(blocking_reasons)
    export_decision = "BLOCK" if export_blocked else "ALLOW"

    return QAReport(
        export_decision=export_decision,
        export_blocked=export_blocked,
        blocking_reasons=blocking_reasons,
        qa_flags=sorted(set(qa_flags)),
        requires_human_review=requires_review,
        template_confidence=template_match.confidence,
        diagram_confidence=diagram.confidence if diagram else None,
        narrative_confidence=narrative.confidence if narrative else None,
        pii_entity_count=pii_entity_count,
        pii_unmapped_count=pii_unmapped_count,
    )
