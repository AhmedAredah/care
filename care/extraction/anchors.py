"""Anchor-based text-slicing helpers.

Phase 9 routes anchor matching through :mod:`anchor_match` so callers
get whitespace/casing normalization plus a bounded fuzzy fallback for
single-character OCR errors. The fuzzy decisions are surfaced to the
extractor via :class:`AnchorSpan` (``start_method``, ``end_method``,
``min_score``) so it can emit informational QA flags without changing
the verbatim text rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .anchor_match import DEFAULT_FUZZY_THRESHOLD, find_anchor


@dataclass(frozen=True)
class AnchorSpan:
    text: str  # extracted span (verbatim, never summarized)
    start_offset: Optional[int]
    end_offset: Optional[int]
    anchor_start_found: bool
    anchor_end_found: bool
    start_method: str = "miss"  # "exact" | "fuzzy" | "miss"
    end_method: str = "miss"
    start_score: float = 0.0
    end_score: float = 0.0

    @property
    def used_fuzzy(self) -> bool:
        """True when at least one anchor needed the fuzzy fallback."""
        return self.start_method == "fuzzy" or self.end_method == "fuzzy"

    @property
    def min_score(self) -> float:
        """Lowest score of the matched anchors (1.0 when no anchors).

        Useful for a single-number "anchor quality" check when emitting
        ``ANCHOR_LOW_CONFIDENCE``.
        """
        scores = []
        if self.anchor_start_found and self.start_score > 0:
            scores.append(self.start_score)
        if self.anchor_end_found and self.end_score > 0:
            scores.append(self.end_score)
        return min(scores) if scores else 1.0


def find_anchor_span(
    page_text: str,
    *,
    anchor_start: Optional[str] = None,
    anchor_end: Optional[str] = None,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    allow_fuzzy: bool = True,
) -> AnchorSpan:
    """Extract the verbatim text between ``anchor_start`` and ``anchor_end``.

    The returned text preserves the original case of ``page_text``.
    Either anchor may be omitted. If an exact match for an anchor
    isn't found and ``allow_fuzzy`` is True, the matcher falls back to
    a SequenceMatcher-ratio sweep over candidate token windows; the
    chosen method is reported on the span.
    """
    haystack = page_text

    start_offset: int = 0
    anchor_start_found = anchor_start is None
    start_method = "miss" if anchor_start else "exact"
    start_score = 1.0 if anchor_start_found else 0.0

    if anchor_start:
        match = find_anchor(
            anchor_start,
            haystack,
            fuzzy_threshold=fuzzy_threshold,
            allow_fuzzy=allow_fuzzy,
        )
        if match.found:
            anchor_start_found = True
            start_method = match.method
            start_score = match.score
            assert match.matched_offset is not None
            start_offset = match.matched_offset + len(match.matched_text or "")

    end_offset: int = len(haystack)
    anchor_end_found = anchor_end is None
    end_method = "miss" if anchor_end else "exact"
    end_score = 1.0 if anchor_end_found else 0.0

    if anchor_end:
        # Search strictly after the start, so an end anchor that
        # physically precedes the start can't be picked up.
        search_from = start_offset if anchor_start_found else 0
        match = find_anchor(
            anchor_end,
            haystack,
            fuzzy_threshold=fuzzy_threshold,
            allow_fuzzy=allow_fuzzy,
            search_from=search_from,
        )
        if match.found:
            anchor_end_found = True
            end_method = match.method
            end_score = match.score
            assert match.matched_offset is not None
            end_offset = match.matched_offset

    if start_offset > end_offset:
        text = ""
    else:
        text = haystack[start_offset:end_offset].strip()

    return AnchorSpan(
        text=text,
        start_offset=start_offset,
        end_offset=end_offset,
        anchor_start_found=anchor_start_found,
        anchor_end_found=anchor_end_found,
        start_method=start_method,
        end_method=end_method,
        start_score=start_score,
        end_score=end_score,
    )
