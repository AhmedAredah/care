"""Diagram crop extraction.

Phase 3 produces an *unredacted* diagram crop in `work_dir`. PII
redaction of the crop lands in Phase 4. The crop must NEVER be placed
under the public export directory.

Phase 7+ adds candidate-page handling and a low-text-density visual
heuristic so a diagram pushed to a different page can still be
located — but only when the visual evidence is consistent. When the
heuristic is uncertain, the extractor flags
``DIAGRAM_CONTINUATION_UNCERTAIN`` and the QA gate blocks export.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image

from ..document_ir.models import DocumentIR, Page
from ..templates.schemas import (
    DiagramContinuation,
    TemplateRegion,
    TemplateSchema,
)
from .region_extractor import bbox_norm_to_pixels, is_valid_bbox_norm


@dataclass
class DiagramExtraction:
    page_index: int
    bbox_norm: tuple[float, float, float, float]
    bbox_pixels: Optional[tuple[int, int, int, int]] = None
    image_path: Optional[str] = None  # path to UNREDACTED crop in work_dir
    confidence: float = 0.0
    requires_review: bool = False
    warnings: list[str] = field(default_factory=list)


def _resolve_candidate_pages(
    region: TemplateRegion,
    document_ir: DocumentIR,
) -> list[int]:
    page_count = len(document_ir.pages)
    diag_cont = region.diagram_continuation
    if diag_cont is not None:
        if isinstance(diag_cont.candidate_pages, list):
            return [p for p in diag_cont.candidate_pages if 0 <= p < page_count]
        return list(range(page_count))
    return [
        p
        for p in region.candidate_pages(page_count=page_count)
        if 0 <= p < page_count
    ]


def _bbox_text_density(
    page: Page,
    bbox_norm: tuple[float, float, float, float],
) -> float:
    """Words inside the normalized bbox / bbox area.

    Words without bboxes are counted at the page level (we can't tell
    whether they fall inside the region). Returns words per unit
    normalized area; lower density = more visual / less text.
    """
    x0, y0, x1, y1 = bbox_norm
    area = max((x1 - x0) * (y1 - y0), 1e-6)
    if not page.words:
        return 0.0
    px_w = max(page.width, 1)
    px_h = max(page.height, 1)
    words_in_bbox = 0
    counted = 0
    for w in page.words:
        if not w.bbox or len(w.bbox) != 4:
            continue
        counted += 1
        wx_norm = (w.bbox[0] / px_w, w.bbox[1] / px_h, w.bbox[2] / px_w, w.bbox[3] / px_h)
        if wx_norm[2] < x0 or wx_norm[0] > x1:
            continue
        if wx_norm[3] < y0 or wx_norm[1] > y1:
            continue
        words_in_bbox += 1
    if counted == 0:
        return 0.0
    return words_in_bbox / area / max(counted, 1) * 100.0  # scaled for readability


def _score_diagram_candidate(
    page_index: int,
    document_ir: DocumentIR,
    bbox_norm: tuple[float, float, float, float],
    source_image_paths: dict[int, Path],
    *,
    diagram_continuation: Optional[DiagramContinuation],
) -> tuple[float, str]:
    """Return ``(score, reason)`` for one diagram-candidate page.

    Score components:
      0.4 base for the page existing.
      +0.5 if a rendered source image is on disk.
      +0.1 bonus when text density inside the bbox is below the
            ``max_text_density`` threshold (i.e. the bbox actually
            looks like a diagram, not a paragraph).
      -0.4 penalty when ``require_visual_density`` is on but density
            is above threshold.
    """
    if not (0 <= page_index < len(document_ir.pages)):
        return 0.0, "out_of_range"
    page = document_ir.pages[page_index]
    score = 0.4
    reason_parts: list[str] = []
    if source_image_paths.get(page_index) is not None and Path(
        source_image_paths[page_index]
    ).exists():
        score += 0.5
        reason_parts.append("image")
    density = _bbox_text_density(page, bbox_norm)
    threshold = (
        diagram_continuation.max_text_density
        if diagram_continuation
        else 0.05
    )
    if density <= threshold:
        score += 0.1
        reason_parts.append(f"low-density({density:.4f})")
    elif diagram_continuation and diagram_continuation.require_visual_density:
        score -= 0.4
        reason_parts.append(f"high-density({density:.4f})")
    return max(score, 0.0), "+".join(reason_parts) or "base"


def extract_diagram(
    template: TemplateSchema,
    document_ir: DocumentIR,
    *,
    work_dir: Path | str,
    source_image_paths: dict[int, Path],
) -> Optional[DiagramExtraction]:
    """Crop the diagram region defined by the matched template.

    Returns None when the template does not declare a diagram region.

    Selection algorithm:
    1. Resolve candidate pages from ``region.diagram_continuation`` if
       present, otherwise from ``region.page``.
    2. Score every candidate page (see :func:`_score_diagram_candidate`).
    3. Pick the highest-scoring page. If two or more candidates tie at
       the top score AND there is more than one candidate, emit
       ``REGION_AMBIGUOUS`` and require review.
    4. If the selected page is not the first declared candidate, emit
       ``DIAGRAM_CANDIDATE_PAGE_USED`` (informational unless review
       was already required).
    """
    region: Optional[TemplateRegion] = template.regions.get("diagram")
    if region is None or region.bbox_norm is None:
        return None

    candidate_pages = region.candidate_pages(
        page_count=len(document_ir.pages)
    )
    diag_cont = region.diagram_continuation
    if diag_cont is not None:
        # diagram_continuation supersedes the region's page list.
        candidate_pages = _resolve_candidate_pages(region, document_ir)

    fallback_page = candidate_pages[0] if candidate_pages else 0

    if not is_valid_bbox_norm(region.bbox_norm):
        return DiagramExtraction(
            page_index=fallback_page,
            bbox_norm=tuple(region.bbox_norm) if region.bbox_norm else (0, 0, 0, 0),
            confidence=0.0,
            requires_review=True,
            warnings=["DIAGRAM_REGION_OUT_OF_BOUNDS"],
        )

    bbox_norm_tuple: tuple[float, float, float, float] = (
        float(region.bbox_norm[0]),
        float(region.bbox_norm[1]),
        float(region.bbox_norm[2]),
        float(region.bbox_norm[3]),
    )

    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)

    valid_pages = [
        p for p in candidate_pages if 0 <= p < len(document_ir.pages)
    ]
    if not valid_pages:
        return DiagramExtraction(
            page_index=fallback_page,
            bbox_norm=bbox_norm_tuple,
            confidence=0.0,
            requires_review=True,
            warnings=["DIAGRAM_REGION_OUT_OF_BOUNDS"],
        )

    # Score every candidate.
    scores: list[tuple[int, float, str]] = []
    for page_index in valid_pages:
        score, reason = _score_diagram_candidate(
            page_index,
            document_ir,
            bbox_norm_tuple,
            source_image_paths,
            diagram_continuation=diag_cont,
        )
        scores.append((page_index, score, reason))

    scores.sort(key=lambda s: (-s[1], valid_pages.index(s[0])))
    best_page, best_score, _best_reason = scores[0]
    warnings: list[str] = []

    # Ambiguity: more than one candidate tied at the top.
    if len(scores) > 1 and scores[0][1] == scores[1][1] and best_score >= 0.5:
        # Only ambiguous when the best is meaningful AND tied. The
        # extractor still produces the crop on the first candidate,
        # but the QA gate blocks via REGION_AMBIGUOUS.
        warnings.append("REGION_AMBIGUOUS")

    if best_page != valid_pages[0]:
        warnings.append("DIAGRAM_CANDIDATE_PAGE_USED")

    source_image = source_image_paths.get(best_page)
    if source_image is None or not Path(source_image).exists():
        warnings.append("DIAGRAM_REGION_UNCERTAIN")
        return DiagramExtraction(
            page_index=best_page,
            bbox_norm=bbox_norm_tuple,
            bbox_pixels=None,
            image_path=None,
            confidence=0.4,
            requires_review=True,
            warnings=warnings,
        )

    # Visual-density gate: when require_visual_density is on, score < 0.6
    # means we couldn't verify the bbox is visually a diagram.
    if (
        diag_cont is not None
        and diag_cont.require_visual_density
        and best_score < 0.6
    ):
        warnings.append("DIAGRAM_CONTINUATION_UNCERTAIN")
        return DiagramExtraction(
            page_index=best_page,
            bbox_norm=bbox_norm_tuple,
            bbox_pixels=None,
            image_path=None,
            confidence=round(best_score, 4),
            requires_review=True,
            warnings=warnings,
        )

    with Image.open(source_image) as img:
        iw, ih = img.size
        bbox_pixels = bbox_norm_to_pixels(bbox_norm_tuple, iw, ih)
        crop = img.crop(bbox_pixels)
        crop_path = work_path / f"diagram_p{best_page}.png"
        crop.save(crop_path, format="PNG")
        image_path = str(crop_path)

    requires_review = "REGION_AMBIGUOUS" in warnings
    return DiagramExtraction(
        page_index=best_page,
        bbox_norm=bbox_norm_tuple,
        bbox_pixels=bbox_pixels,
        image_path=image_path,
        confidence=0.9 if not requires_review else 0.5,
        requires_review=requires_review,
        warnings=warnings,
    )
