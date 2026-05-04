"""Narrative extraction.

Phase 3 produces a verbatim narrative slice from the page text bounded
by ``anchor_start``/``anchor_end``. The result is unredacted; PII
redaction lands in Phase 4. Narrative must never be summarized or
rewritten.

Phase 7+ adds:

- **Confidence-scored candidate selection.** Every candidate page
  gets a score; the highest-scoring page wins. Ties on the top
  score → ``REGION_AMBIGUOUS`` → blocked.
- **Expanded continuation.** ``continue_until_anchor_found``,
  ``max_continuation_pages``, ``stop_at_next_section_anchor``, and
  ``require_review_if_anchor_end_missing`` are all honored.
- **Shifted-region search.** When the primary candidates score below
  ``shifted_region_search.min_primary_score`` and the search is
  enabled, the extractor scans additional pages for the same
  anchors. A successful shift surfaces ``REGION_SHIFTED_PAGE``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..document_ir.models import DocumentIR
from ..templates.schemas import (
    ContinuationSpec,
    TemplateRegion,
    TemplateSchema,
)
from .anchor_match import find_anchor
from .anchors import find_anchor_span

ANCHOR_LOW_CONFIDENCE_THRESHOLD = 0.92
"""Below this anchor-match score, surface ANCHOR_LOW_CONFIDENCE.

Slightly above the fuzzy floor (0.85) so the flag fires *before* a
match is so degraded that it's near the rejection edge — operators
get a heads-up while the match is still usable."""


@dataclass
class NarrativeExtraction:
    page_index: int
    text: str  # verbatim
    anchor_start: str | None = None
    anchor_end: str | None = None
    anchor_start_found: bool = False
    anchor_end_found: bool = False
    bbox_norm: tuple[float, float, float, float] | None = None
    bbox_pixels: tuple[int, int, int, int] | None = None
    confidence: float = 0.0
    requires_review: bool = False
    warnings: list[str] = field(default_factory=list)
    text_source: str = "unknown"
    spans_pages: list[int] = field(default_factory=list)


# ----- helpers ------------------------------------------------------------


def _page_text(document_ir: DocumentIR, page_index: int) -> str:
    if page_index < 0 or page_index >= len(document_ir.pages):
        return ""
    return " ".join(w.text for w in document_ir.pages[page_index].words)


def _candidate_pages_for(
    region: TemplateRegion, document_ir: DocumentIR
) -> list[int]:
    page_count = len(document_ir.pages)
    candidates = region.candidate_pages(page_count=page_count)
    return [p for p in candidates if 0 <= p < page_count]


def _score_page(
    page_index: int,
    region: TemplateRegion,
    document_ir: DocumentIR,
) -> float:
    """Score a candidate page for narrative occupancy (Phase 9 aware).

    Uses the normalized + fuzzy anchor matcher so an OCR misread of
    ``"Narrative"`` as ``"Narrahve"`` doesn't drop a perfectly good
    page from contention. Fuzzy matches are discounted slightly so an
    exact-match page outscores a fuzzy-match page on tied criteria.

    1.0  — both anchors declared, both found exact
    0.92 — both anchors, at least one fuzzy
    0.7  — only anchor_start found
    0.5  — only anchor_end found
    0.3  — neither anchor declared (bbox-only) — boundaries uncertain
    0.0  — declared anchors missing
    """
    page_text = _page_text(document_ir, page_index)
    has_start_match = (
        find_anchor(region.anchor_start, page_text)
        if region.anchor_start
        else None
    )
    has_end_match = (
        find_anchor(region.anchor_end, page_text)
        if region.anchor_end
        else None
    )
    has_start = bool(has_start_match and has_start_match.found)
    has_end = bool(has_end_match and has_end_match.found)
    fuzzy_used = (
        (has_start_match and has_start_match.is_fuzzy)
        or (has_end_match and has_end_match.is_fuzzy)
    )

    if region.anchor_start and region.anchor_end:
        if has_start and has_end:
            return 0.92 if fuzzy_used else 1.0
        if has_start:
            return 0.66 if (has_start_match and has_start_match.is_fuzzy) else 0.7
        if has_end:
            return 0.46 if (has_end_match and has_end_match.is_fuzzy) else 0.5
        return 0.0
    if region.anchor_start:
        if not has_start:
            return 0.0
        return 0.85 if (has_start_match and has_start_match.is_fuzzy) else 0.9
    if region.anchor_end:
        if not has_end:
            return 0.0
        return 0.46 if (has_end_match and has_end_match.is_fuzzy) else 0.5
    return 0.3  # bbox-only narrative — boundaries uncertain


def _empty_extraction(region: TemplateRegion) -> NarrativeExtraction:
    candidates = region.candidate_pages(page_count=0)
    page_index = candidates[0] if candidates else 0
    return NarrativeExtraction(
        page_index=page_index,
        text="",
        anchor_start=region.anchor_start,
        anchor_end=region.anchor_end,
        confidence=0.0,
        requires_review=True,
        warnings=["NARRATIVE_BOUNDARIES_UNCERTAIN"],
    )


def _resolve_continuation_pages(
    continuation: ContinuationSpec, document_ir: DocumentIR
) -> list[int]:
    page_count = len(document_ir.pages)
    if isinstance(continuation.pages, list):
        return [p for p in continuation.pages if 0 <= p < page_count]
    return list(range(page_count))


def _consume_continuation(
    document_ir: DocumentIR,
    primary_page: int,
    continuation: ContinuationSpec,
) -> tuple[str, list[int], bool, bool]:
    """Walk continuation pages.

    Returns ``(appended_text, pages_spanned, anchor_end_found, truncated)``.

    ``truncated`` is True when the loop exited because of
    ``max_continuation_pages`` rather than finding the end anchor.
    """
    appended_chunks: list[str] = []
    spanned: list[int] = []
    end_anchor = (continuation.anchor_end or "").lower()
    section_stops = continuation.stop_at_next_section_anchor or []
    if isinstance(section_stops, str):
        section_stops = [section_stops]
    section_stops_lower = [s.lower() for s in section_stops if s]

    pages_to_walk = [
        p for p in _resolve_continuation_pages(continuation, document_ir) if p != primary_page
    ]

    consumed = 0
    truncated = False
    for page_index in pages_to_walk:
        if consumed >= continuation.max_continuation_pages:
            truncated = True
            break
        page_text = _page_text(document_ir, page_index)
        spanned.append(page_index)
        consumed += 1

        # Stop early at a "next section" anchor.
        cutoff_section: int | None = None
        if section_stops_lower:
            text_lower = page_text.lower()
            for sa in section_stops_lower:
                idx = text_lower.find(sa)
                if idx >= 0 and (cutoff_section is None or idx < cutoff_section):
                    cutoff_section = idx

        # End anchor on this page?
        if end_anchor and continuation.continue_until_anchor_found:
            text_lower = page_text.lower()
            end_idx = text_lower.find(end_anchor)
            if end_idx >= 0 and (cutoff_section is None or end_idx <= cutoff_section):
                appended_chunks.append(page_text[:end_idx])
                return (
                    "\n".join(c for c in appended_chunks if c).strip(),
                    spanned,
                    True,
                    False,
                )

        if cutoff_section is not None:
            appended_chunks.append(page_text[:cutoff_section])
            return (
                "\n".join(c for c in appended_chunks if c).strip(),
                spanned,
                not end_anchor,  # no end anchor declared = trivially "found"
                False,
            )

        appended_chunks.append(page_text)

    return (
        "\n".join(c for c in appended_chunks if c).strip(),
        spanned,
        not end_anchor,  # exhausted without finding end anchor
        truncated,
    )


def _shifted_search(
    region: TemplateRegion,
    document_ir: DocumentIR,
    primary_pages: set[int],
) -> int | None:
    """Scan ``shifted_region_search.search_pages`` (excluding primary
    candidates) for the same anchor labels. Return the best-scoring
    page, or None."""
    sr = region.shifted_region_search
    if sr is None or not sr.enabled:
        return None
    page_count = len(document_ir.pages)
    if isinstance(sr.search_pages, list):
        candidates = [p for p in sr.search_pages if 0 <= p < page_count]
    else:
        candidates = list(range(page_count))
    candidates = [p for p in candidates if p not in primary_pages]
    if not candidates:
        return None
    scored = [(_score_page(p, region, document_ir), p) for p in candidates]
    scored.sort(key=lambda x: (-x[0], x[1]))
    best_score, best_page = scored[0]
    if best_score >= sr.min_primary_score:
        return best_page
    return None


def _select_primary(
    region: TemplateRegion, document_ir: DocumentIR
) -> tuple[int | None, list[str], bool]:
    """Score every candidate and pick the best.

    Returns ``(page_index_or_None, warnings, ambiguous)``.
    """
    candidates = _candidate_pages_for(region, document_ir)
    if not candidates:
        return None, [], False

    scored = [(_score_page(p, region, document_ir), idx, p) for idx, p in enumerate(candidates)]
    scored.sort(key=lambda x: (-x[0], x[1]))
    best_score, _, best_page = scored[0]

    warnings: list[str] = []
    ambiguous = False
    if (
        len(scored) > 1
        and scored[0][0] == scored[1][0]
        and best_score >= 0.7
    ):
        ambiguous = True
        warnings.append("REGION_AMBIGUOUS")

    page_search = region.page_search()
    if page_search.search_strategy == "first_match":
        # Honor first-match: pick the first candidate whose score is non-zero.
        for score, _, candidate in [(s, i, p) for s, i, p in [
            (_score_page(p, region, document_ir), idx, p)
            for idx, p in enumerate(candidates)
        ]]:
            if score > 0:
                best_page = candidate
                best_score = score
                break

    if best_score == 0:
        return None, warnings, ambiguous
    return best_page, warnings, ambiguous


# ----- main ---------------------------------------------------------------


def extract_narrative(
    template: TemplateSchema,
    document_ir: DocumentIR,
) -> NarrativeExtraction | None:
    """Slice the page-text between the template's narrative anchors."""
    region: TemplateRegion | None = template.regions.get("narrative")
    if region is None:
        return None

    primary_candidates = set(_candidate_pages_for(region, document_ir))
    primary_page, primary_warnings, ambiguous = _select_primary(region, document_ir)

    shifted = False
    if primary_page is None:
        # Try shifted search before giving up.
        shifted_pick = _shifted_search(region, document_ir, primary_candidates)
        if shifted_pick is None:
            return _empty_extraction(region)
        primary_page = shifted_pick
        shifted = True

    page = document_ir.pages[primary_page]
    primary_text = _page_text(document_ir, primary_page)

    span = find_anchor_span(
        primary_text,
        anchor_start=region.anchor_start,
        anchor_end=region.anchor_end,
    )

    warnings: list[str] = list(primary_warnings)
    spans_pages: list[int] = [primary_page]
    anchor_end_resolved = span.anchor_end_found
    text_out = span.text
    truncated = False

    if shifted:
        warnings.append("REGION_SHIFTED_PAGE")

    # Continuation handling — only when narrative anchor_end is declared
    # but missing on the primary page AND a continuation block exists.
    continuation = region.continuation
    if (
        region.anchor_end
        and not span.anchor_end_found
        and continuation is not None
    ):
        cont_text, cont_pages, cont_end_found, cont_truncated = _consume_continuation(
            document_ir, primary_page, continuation
        )
        if cont_pages:
            spans_pages.extend(cont_pages)
            warnings.append("NARRATIVE_CONTINUED")
            warnings.append("NARRATIVE_SPANS_PAGES")
        if cont_text:
            primary_after = (
                primary_text[span.start_offset :]
                if span.start_offset is not None
                else primary_text
            )
            text_out = (primary_after + "\n" + cont_text).strip()
        anchor_end_resolved = cont_end_found
        truncated = cont_truncated
        if truncated:
            warnings.append("NARRATIVE_CONTINUATION_TRUNCATED")
        if (
            not cont_end_found
            and continuation.require_review_if_anchor_end_missing
        ):
            warnings.append("NARRATIVE_CONTINUATION_ANCHOR_MISSING")

    declared_anchors = sum(1 for a in (region.anchor_start, region.anchor_end) if a)
    found_anchors = (
        (1 if region.anchor_start and span.anchor_start_found else 0)
        + (1 if region.anchor_end and anchor_end_resolved else 0)
    )

    requires_review = ambiguous or shifted or False

    if shifted and region.shifted_region_search and region.shifted_region_search.require_review_on_shift:
        requires_review = True

    if declared_anchors and found_anchors < declared_anchors:
        warnings.append("NARRATIVE_ANCHORS_NOT_FOUND")
        requires_review = True

    # Phase 9: surface fuzzy match + low-confidence informational flags.
    # These are warn-only — they NEVER block export. They tell the
    # operator "we got something, but you may want to eyeball it."
    if span.used_fuzzy:
        warnings.append("NARRATIVE_ANCHORS_FUZZY_MATCHED")
    if span.min_score < ANCHOR_LOW_CONFIDENCE_THRESHOLD:
        warnings.append("ANCHOR_LOW_CONFIDENCE")

    if not text_out:
        warnings.append("NARRATIVE_EMPTY")
        requires_review = True

    if declared_anchors == 0:
        warnings.append("NARRATIVE_BOUNDARIES_UNCERTAIN")
        requires_review = True
        confidence = 0.3
    elif declared_anchors == 2 and found_anchors == 2:
        confidence = 0.9
    elif declared_anchors == 1 and found_anchors == 1:
        confidence = 0.7
    else:
        confidence = 0.4

    if not text_out:
        confidence = 0.0
    if ambiguous:
        confidence = min(confidence, 0.5)

    bbox_norm_tuple: tuple[float, float, float, float] | None = None
    bbox_pixels: tuple[int, int, int, int] | None = None
    if region.bbox_norm is not None:
        bbox_norm_tuple = (
            float(region.bbox_norm[0]),
            float(region.bbox_norm[1]),
            float(region.bbox_norm[2]),
            float(region.bbox_norm[3]),
        )
        bbox_pixels = (
            int(bbox_norm_tuple[0] * page.width),
            int(bbox_norm_tuple[1] * page.height),
            int(bbox_norm_tuple[2] * page.width),
            int(bbox_norm_tuple[3] * page.height),
        )

    # Dedup warnings while preserving first-occurrence order.
    seen: set[str] = set()
    deduped: list[str] = []
    for w in warnings:
        if w in seen:
            continue
        seen.add(w)
        deduped.append(w)

    return NarrativeExtraction(
        page_index=primary_page,
        text=text_out,
        anchor_start=region.anchor_start,
        anchor_end=region.anchor_end,
        anchor_start_found=span.anchor_start_found,
        anchor_end_found=anchor_end_resolved,
        bbox_norm=bbox_norm_tuple,
        bbox_pixels=bbox_pixels,
        confidence=round(confidence, 4),
        requires_review=requires_review,
        warnings=deduped,
        text_source=page.text_source,
        spans_pages=spans_pages,
    )
