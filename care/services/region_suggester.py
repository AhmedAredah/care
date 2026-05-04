"""Region suggester (Phase 11).

Two backends, both **suggestion-only**:

1. **LayoutLM** — when the plugin is enabled and loaded, calls its
   ``detect_regions`` method, converts each output's bbox from
   LayoutLM's 0-1000 integer space to our normalized [0..1] space,
   and labels the suggestion accordingly.
2. **Heuristic** — pure-Python, no ML. Splits the page into N
   horizontal bands by word density and proposes the lowest-density
   band as a diagram candidate and the highest-density band as a
   narrative candidate. Useful as a default starting point when no
   LayoutLM model files are deployed.

Both backends return the same shape so the frontend doesn't care
which produced the suggestion. The suggestion is **never** applied
automatically — the operator must click Accept in the builder UI for
it to enter the template.

Output safety guarantees (mirrored on every suggestion record):

- ``requires_review`` is always ``True``.
- ``source`` discloses the backend (``"layoutlm"`` or ``"heuristic"``)
  so operators can filter by trust level.
- The endpoint surfaces ``LAYOUTLM_*`` QA flags only when LayoutLM
  produced the suggestion. Heuristic suggestions carry no QA flags
  because they are not model output.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from ..document_ai.base import DocumentAIProvider
from ..services.template_builder import BuilderPage

_log = logging.getLogger(__name__)


@dataclass
class RegionSuggestion:
    page_index: int
    label: str  # "diagram" | "narrative" | other
    bbox_norm: list[float]  # [x0, y0, x1, y1] in [0..1]
    confidence: float
    source: str  # "layoutlm" | "heuristic"
    requires_review: bool = True
    suggestion_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def suggest_regions_for_page(
    page: BuilderPage,
    *,
    layoutlm_provider: DocumentAIProvider | None = None,
    band_count: int = 4,
) -> tuple[list[RegionSuggestion], list[str]]:
    """Return ``(suggestions, qa_flags)`` for one builder page.

    When ``layoutlm_provider`` is supplied, it's tried first. The
    plugin's ``detect_regions`` may return an empty list (skeleton
    mode in CI) — in that case we fall through to the heuristic so
    the UI always has something to show.

    QA flags are emitted **only** when LayoutLM produced any
    suggestion. The heuristic backend is deterministic and review-
    gated by the UI's accept-step, so it doesn't need to add flags
    that would force ``requires_human_review`` on the eventual
    pipeline run (the operator's accept-step is the human review).
    """
    qa_flags: list[str] = []
    if layoutlm_provider is not None:
        ll = _from_layoutlm(layoutlm_provider, page)
        if ll:
            qa_flags = [
                "LAYOUTLM_PLUGIN_USED",
                "LAYOUTLM_REGION_SUGGESTION",
                "LAYOUTLM_REQUIRES_REVIEW",
            ]
            return ll, qa_flags

    return _from_heuristic(page, band_count=band_count), qa_flags


def _from_layoutlm(
    provider: DocumentAIProvider, page: BuilderPage
) -> list[RegionSuggestion]:
    try:
        result = provider.detect_regions(
            image=str(page.image_path),
            page_context={"page_index": page.index},
        )
    except NotImplementedError:
        return []
    except Exception as exc:  # noqa: BLE001 — never break the pipeline
        _log.warning("LayoutLM detect_regions failed: %s", exc)
        return []

    out: list[RegionSuggestion] = []
    for i, region in enumerate(result.regions or []):
        if not region.bbox or len(region.bbox) != 4:
            continue
        # LayoutLM uses 0-1000 integer normalization. Convert to [0..1].
        x0, y0, x1, y1 = region.bbox
        if max(x1, y1) > 1.0:  # 0-1000 space
            x0, y0, x1, y1 = x0 / 1000.0, y0 / 1000.0, x1 / 1000.0, y1 / 1000.0
        x0, y0, x1, y1 = _clamp_bbox(x0, y0, x1, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        out.append(
            RegionSuggestion(
                page_index=page.index,
                label=region.label or "region",
                bbox_norm=[x0, y0, x1, y1],
                confidence=float(region.confidence or 0.0),
                source="layoutlm",
                suggestion_id=f"layoutlm_p{page.index}_{i}",
            )
        )
    return out


def _from_heuristic(
    page: BuilderPage, *, band_count: int
) -> list[RegionSuggestion]:
    """Density-band heuristic: split the page vertically into N bands;
    propose the lowest-density band as ``diagram`` and the highest-
    density band as ``narrative``."""
    if band_count < 2 or page.height <= 0 or page.width <= 0:
        return []
    if not page.words:
        # No native words — image-only PDF. Fall back to a single
        # diagram suggestion covering the upper 60% of the page so the
        # UI has something to show.
        return [
            RegionSuggestion(
                page_index=page.index,
                label="diagram",
                bbox_norm=[0.05, 0.05, 0.95, 0.6],
                confidence=0.3,
                source="heuristic",
                suggestion_id=f"heur_p{page.index}_diag_default",
            )
        ]

    band_height = page.height / band_count
    band_counts = [0] * band_count
    for w in page.words:
        if not w.bbox or len(w.bbox) != 4:
            continue
        # word bbox is in image-pixel space at session DPI
        cy = (w.bbox[1] + w.bbox[3]) / 2.0
        band = min(int(cy / band_height), band_count - 1)
        if band >= 0:
            band_counts[band] += 1

    total = sum(band_counts) or 1
    # Score each band by how *not* like a diagram it is — fewer words
    # = more diagram-like. We propose ONE diagram and ONE narrative
    # band; the operator refines from there.
    densest = max(range(band_count), key=lambda i: band_counts[i])
    sparsest = min(range(band_count), key=lambda i: band_counts[i])

    out: list[RegionSuggestion] = []

    # Diagram suggestion — sparsest band.
    if band_counts[sparsest] < band_counts[densest]:
        y0 = sparsest * band_height / page.height
        y1 = (sparsest + 1) * band_height / page.height
        # Confidence: fraction of "missingness" of words in this band.
        diagram_confidence = round(1.0 - band_counts[sparsest] / total, 4)
        out.append(
            RegionSuggestion(
                page_index=page.index,
                label="diagram",
                bbox_norm=_clamp_bbox(0.04, y0, 0.96, y1),
                confidence=diagram_confidence,
                source="heuristic",
                suggestion_id=f"heur_p{page.index}_diag_b{sparsest}",
            )
        )

    # Narrative suggestion — densest band.
    y0n = densest * band_height / page.height
    y1n = (densest + 1) * band_height / page.height
    narrative_confidence = round(band_counts[densest] / total, 4)
    out.append(
        RegionSuggestion(
            page_index=page.index,
            label="narrative",
            bbox_norm=_clamp_bbox(0.04, y0n, 0.96, y1n),
            confidence=narrative_confidence,
            source="heuristic",
            suggestion_id=f"heur_p{page.index}_narr_b{densest}",
        )
    )
    return out


def _clamp_bbox(x0: float, y0: float, x1: float, y1: float) -> list[float]:
    def clamp(v: float) -> float:
        return max(0.0, min(1.0, v))

    return [clamp(x0), clamp(y0), clamp(x1), clamp(y1)]
