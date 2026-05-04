"""DocumentIR reconciliation.

Phase 5 reconciliation merges *alternative* DocumentIRs (typically VLM
spatial OCR output) into a *base* DocumentIR (typically native PDF text
or traditional OCR). The result preserves provenance for every word
and emits QA warnings for:

- VLM_USED_FOR_EXTRACTION                — any VLM source contributed
- VLM_OUTPUT_HAS_NO_BBOXES               — alt source word lacks bbox
- VLM_OUTPUT_CONFLICTS_WITH_OCR          — alt text disagrees at the same span
- VLM_GENERATIVE_OUTPUT_REQUIRES_REVIEW  — alt source is generative

Important rule: VLM-only text without bboxes is *never* added to the
base words. It is recorded only as warnings so the QA gate can decide
whether human review is required. Image redaction must continue to
draw bboxes only from base (non-generative) sources.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from .models import AlternativeSource, DocumentIR, Page, Warning, Word


@dataclass
class AlternativeSourceDoc:
    """An alternative DocumentIR + provenance metadata about its provider."""

    document_ir: DocumentIR
    provider_name: str
    generative: bool = False
    hallucination_risk: bool = False


@dataclass
class ReconciliationResult:
    document_ir: DocumentIR
    warnings: list[Warning] = field(default_factory=list)


def reconcile_with_alternatives(
    base: DocumentIR,
    alternatives: Iterable[AlternativeSourceDoc],
) -> ReconciliationResult:
    """Annotate `base` with cross-source evidence from each alternative.

    `base.pages[*].words[*]` is mutated in-place to receive `AlternativeSource`
    entries for every overlapping alt word that maps to image coordinates.
    Alt words without bboxes never enter `alternative_sources` (they could
    not drive image redaction).
    """
    warnings: list[Warning] = []
    saw_any_vlm = False
    saw_generative = False

    base_pages_by_index: dict[int, Page] = {p.page_index: p for p in base.pages}

    for alt in alternatives:
        if alt.generative:
            saw_generative = True

        for alt_page in alt.document_ir.pages:
            base_page: Page | None = base_pages_by_index.get(alt_page.page_index)
            if base_page is None:
                continue
            for alt_word in alt_page.words:
                if alt_word.bbox is None:
                    warnings.append(
                        Warning(
                            code="VLM_OUTPUT_HAS_NO_BBOXES",
                            message=(
                                f"Alternative source '{alt.provider_name}' "
                                f"emitted text without a bbox on page "
                                f"{alt_page.page_index}; cannot drive image "
                                f"redaction."
                            ),
                            page_index=alt_page.page_index,
                        )
                    )
                    saw_any_vlm = saw_any_vlm or alt.generative
                    continue

                best, best_overlap = _best_overlapping_word(base_page.words, alt_word.bbox)
                if best is None:
                    # No overlap with any base word — VLM-only token.
                    warnings.append(
                        Warning(
                            code="VLM_USED_FOR_EXTRACTION",
                            message=(
                                f"Alternative source '{alt.provider_name}' "
                                f"contributed text at page {alt_page.page_index} "
                                f"with no matching base word."
                            ),
                            page_index=alt_page.page_index,
                        )
                    )
                    saw_any_vlm = True
                    if alt.generative:
                        warnings.append(
                            Warning(
                                code="VLM_GENERATIVE_OUTPUT_REQUIRES_REVIEW",
                                message=(
                                    f"Generative alternative '{alt.provider_name}' "
                                    f"text on page {alt_page.page_index} "
                                    f"requires human review."
                                ),
                                page_index=alt_page.page_index,
                            )
                        )
                    continue

                if _texts_disagree(best.text, alt_word.text):
                    warnings.append(
                        Warning(
                            code="VLM_OUTPUT_CONFLICTS_WITH_OCR",
                            message=(
                                f"Alternative source '{alt.provider_name}' "
                                f"disagrees with base '{best.source}' on page "
                                f"{alt_page.page_index} (overlap area {best_overlap})."
                            ),
                            page_index=alt_page.page_index,
                        )
                    )

                best.alternative_sources.append(
                    AlternativeSource(
                        provider=alt.provider_name,
                        text=alt_word.text,
                        confidence=alt_word.confidence,
                        bbox=list(alt_word.bbox),
                    )
                )
                saw_any_vlm = True

    if saw_any_vlm:
        warnings.append(
            Warning(
                code="VLM_USED_FOR_EXTRACTION",
                message="At least one VLM/document-AI alternative source contributed evidence.",
            )
        )
    if saw_generative:
        warnings.append(
            Warning(
                code="VLM_GENERATIVE_OUTPUT_REQUIRES_REVIEW",
                message=(
                    "Generative alternative sources contributed; reviewer must "
                    "confirm before public export."
                ),
            )
        )

    return ReconciliationResult(document_ir=base, warnings=_dedup_warnings(warnings))


def _best_overlapping_word(words: list[Word], target_bbox: list[float]) -> tuple[Word | None, float]:
    tx0, ty0, tx1, ty1 = target_bbox
    best: Word | None = None
    best_overlap = 0.0
    for word in words:
        if not word.bbox:
            continue
        wx0, wy0, wx1, wy1 = word.bbox
        ix0 = max(tx0, wx0)
        iy0 = max(ty0, wy0)
        ix1 = min(tx1, wx1)
        iy1 = min(ty1, wy1)
        if ix1 <= ix0 or iy1 <= iy0:
            continue
        overlap = (ix1 - ix0) * (iy1 - iy0)
        if overlap > best_overlap:
            best_overlap = overlap
            best = word
    return best, best_overlap


def _texts_disagree(a: str, b: str) -> bool:
    """Loose text-equality check — case-insensitive, strips punctuation noise."""
    norm_a = "".join(c.lower() for c in a if c.isalnum())
    norm_b = "".join(c.lower() for c in b if c.isalnum())
    return norm_a != norm_b


def _dedup_warnings(warnings: list[Warning]) -> list[Warning]:
    seen: set[tuple[str, int | None, str]] = set()
    out: list[Warning] = []
    for w in warnings:
        key = (w.code, w.page_index, w.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out
