"""Template YAML schema.

Phase 7+ supports content-reflow tolerance via three optional surfaces
on each ``TemplateRegion``:

- ``page`` accepts ``int``, ``list[int]``, the literal string ``"any"``,
  or a structured :class:`PageSearch` object (``candidate_pages`` +
  ``search_strategy``). Each candidate page is scored independently
  by the extractor; the best-scoring page wins. Ties on the highest
  score are treated as ambiguity → fail-closed review.
- ``continuation`` declares overflow handling: how far the narrative
  may spill, what end anchor closes it, whether to stop early at a
  later section's anchor, and whether anchor-end-missing is a
  blocking condition.
- ``shifted_region_search`` lets the extractor look on neighboring
  pages when the primary candidate is empty, before falling back to
  fail-closed review.

Diagram regions additionally support ``diagram_continuation`` with
candidate-page handling and a low-text-density heuristic so a diagram
that gets pushed to a different page can still be picked up — but
only when the visual evidence supports it.

Existing single-page templates remain valid without modification.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PageSpec = int | list[int] | Literal["any"]
PageSearchStrategy = Literal["first_match", "best_match", "fixed", "any"]


# ----- shared validators ---------------------------------------------------


def _validate_bbox_norm(value: list[float] | None) -> list[float] | None:
    if value is None:
        return value
    if len(value) != 4:
        raise ValueError("bbox_norm must have exactly 4 values [x0, y0, x1, y1]")
    x0, y0, x1, y1 = value
    if not (0 <= x0 < x1 <= 1) or not (0 <= y0 < y1 <= 1):
        raise ValueError(
            f"bbox_norm values must satisfy 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1; got {value}"
        )
    return [float(x0), float(y0), float(x1), float(y1)]


def _normalize_page_list(value: list[int]) -> list[int]:
    if not value:
        raise ValueError("page list must not be empty")
    out: list[int] = []
    seen: set[int] = set()
    for entry in value:
        if isinstance(entry, bool) or not isinstance(entry, int):
            raise ValueError("page list entries must be ints")
        if entry < 0:
            raise ValueError("page list entries must be >= 0")
        if entry in seen:
            continue
        seen.add(entry)
        out.append(entry)
    return out


def _validate_page_spec(value):
    if value == "any":
        return "any"
    if isinstance(value, bool):
        raise ValueError("page must be int, list[int], 'any', or PageSearch")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("page must be >= 0")
        return value
    if isinstance(value, list):
        return _normalize_page_list(value)
    if isinstance(value, dict):
        # forwarded into PageSearch validation downstream
        return value
    if isinstance(value, PageSearch):
        return value
    raise ValueError("page must be int, list[int], 'any', or PageSearch")


# ----- objects -------------------------------------------------------------


class TemplateSignature(BaseModel):
    model_config = ConfigDict(extra="forbid")
    anchor_text: list[str] = Field(default_factory=list)
    form_number_regex: str | None = None


class TemplateLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_count_min: int = 1
    page_count_max: int = 99


class PageSearch(BaseModel):
    """Structured candidate-page selector.

    ``candidate_pages`` accepts a list of explicit page indices or the
    string ``"any"`` (meaning every page in the doc). ``search_strategy``
    selects how the extractor picks the winning page when multiple
    candidates are scored:

    - ``"best_match"`` — score every candidate, pick the highest. Ties
      on the highest score → fail-closed ambiguity.
    - ``"first_match"`` — first candidate (in declared order) with
      score above the per-region threshold wins.
    - ``"fixed"`` — only the first declared candidate page is tried;
      everything else is ignored. Equivalent to a singleton list.
    - ``"any"`` — alias for ``best_match`` over every page.
    """

    model_config = ConfigDict(extra="forbid")
    candidate_pages: PageSpec = "any"
    search_strategy: PageSearchStrategy = "best_match"

    @field_validator("candidate_pages", mode="before")
    @classmethod
    def _check_pages(cls, value):
        return _validate_page_spec(value)


class ShiftedRegionSearch(BaseModel):
    """Fallback search when the primary region is empty / low confidence.

    The extractor first tries the region's declared candidate pages.
    If the best score is below ``min_primary_score`` and this object
    is enabled, it scans ``search_pages`` (default ``"any"``) for the
    same anchor labels and may select one of those pages. The shifted
    page is reported via the ``REGION_SHIFTED_PAGE`` QA flag.
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    search_pages: PageSpec = "any"
    min_primary_score: float = 0.5
    require_review_on_shift: bool = True

    @field_validator("search_pages", mode="before")
    @classmethod
    def _check_pages(cls, value):
        return _validate_page_spec(value)


class ContinuationSpec(BaseModel):
    """Narrative-overflow descriptor.

    Used when the narrative body may continue onto subsequent pages
    until ``anchor_end`` is finally found. The extractor concatenates
    each candidate continuation page's text in order, stopping at:

    - ``anchor_end`` when ``continue_until_anchor_found`` is true (the
      default), OR
    - the first occurrence of any string in
      ``stop_at_next_section_anchor`` (e.g. "Witness Statement"), OR
    - after ``max_continuation_pages`` pages have been consumed.

    If ``require_review_if_anchor_end_missing`` is true (the default)
    AND the anchor was never matched, the QA gate flags
    ``NARRATIVE_CONTINUATION_ANCHOR_MISSING`` and blocks export.
    """

    model_config = ConfigDict(extra="forbid")
    pages: PageSpec = "any"
    anchor_end: str | None = None
    bbox_norm: list[float] | None = None
    continue_until_anchor_found: bool = True
    max_continuation_pages: int = 3
    stop_at_next_section_anchor: str | list[str] | None = None
    require_review_if_anchor_end_missing: bool = True

    @field_validator("pages", mode="before")
    @classmethod
    def _check_pages(cls, value):
        return _validate_page_spec(value)

    @field_validator("bbox_norm")
    @classmethod
    def _check_bbox(cls, value: list[float] | None) -> list[float] | None:
        return _validate_bbox_norm(value)

    @field_validator("max_continuation_pages")
    @classmethod
    def _check_max(cls, value: int) -> int:
        if value < 0:
            raise ValueError("max_continuation_pages must be >= 0")
        return value


class DiagramContinuation(BaseModel):
    """Diagram-specific candidate-page handling.

    Diagrams don't reflow text; they get pushed to a different page
    when surrounding content overflows. ``candidate_pages`` lists
    where the diagram could live. The extractor scores each page by
    the *visual density* heuristic — the bbox area's text density,
    inverted (less text = more likely to be a diagram).

    If ``require_visual_density`` is true, the chosen page must have
    a text density below ``max_text_density``; otherwise the
    extraction is marked uncertain.
    """

    model_config = ConfigDict(extra="forbid")
    candidate_pages: PageSpec = "any"
    require_visual_density: bool = False
    max_text_density: float = 0.05  # words per 1.0 normalized bbox-area
    require_review_if_uncertain: bool = True

    @field_validator("candidate_pages", mode="before")
    @classmethod
    def _check_pages(cls, value):
        return _validate_page_spec(value)


class TemplateRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ``page`` is the canonical candidate-page selector. Can be a
    # single int (pinned), a list of ints (priority order), the
    # string "any" (every page), or a full PageSearch object.
    page: int | list[int] | Literal["any"] | PageSearch = 0
    bbox_norm: list[float] | None = None
    anchor_start: str | None = None
    anchor_end: str | None = None
    requires_redaction: bool = False
    continuation: ContinuationSpec | None = None
    shifted_region_search: ShiftedRegionSearch | None = None
    diagram_continuation: DiagramContinuation | None = None

    @field_validator("page", mode="before")
    @classmethod
    def _check_page(cls, value):
        return _validate_page_spec(value)

    @field_validator("bbox_norm")
    @classmethod
    def _check_bbox(cls, value: list[float] | None) -> list[float] | None:
        return _validate_bbox_norm(value)

    def page_search(self) -> PageSearch:
        """Project ``page`` to a normalized :class:`PageSearch` object."""
        if isinstance(self.page, PageSearch):
            return self.page
        if isinstance(self.page, list):
            return PageSearch(candidate_pages=list(self.page), search_strategy="best_match")
        if self.page == "any":
            return PageSearch(candidate_pages="any", search_strategy="best_match")
        return PageSearch(candidate_pages=[int(self.page)], search_strategy="fixed")

    def candidate_pages(self, *, page_count: int | None = None) -> list[int]:
        """Return concrete candidate page indices, expanding ``"any"``
        against ``page_count`` if provided. Without ``page_count`` the
        list is returned in declared order; ``"any"`` collapses to an
        empty list (caller is expected to know the doc length)."""
        ps = self.page_search()
        if isinstance(ps.candidate_pages, list):
            return list(ps.candidate_pages)
        # "any" — needs page_count to materialize
        if page_count is None or page_count <= 0:
            return []
        return list(range(page_count))


class TemplateSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_id: str
    jurisdiction: str | None = None
    agency: str | None = None
    version: str = "0"
    description: str | None = None
    extends: str | None = None
    signature: TemplateSignature = Field(default_factory=TemplateSignature)
    layout: TemplateLayout = Field(default_factory=TemplateLayout)
    regions: dict[str, TemplateRegion] = Field(default_factory=dict)
