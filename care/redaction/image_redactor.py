"""Pixel-level image redaction.

Black filled rectangles over PII bboxes. The boxes are expanded by a
few pixels to absorb OCR coordinate uncertainty.
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageDraw

from ..pii.entities import PIIEntity
from .policies import DEFAULT_BBOX_EXPANSION_PX


def redact_image(
    source_image: Path | str,
    entities_with_bboxes: Iterable[PIIEntity],
    output_path: Path | str,
    *,
    expand_px: int = DEFAULT_BBOX_EXPANSION_PX,
    fill: str = "black",
) -> Path:
    """Mask every entity with a usable bbox; save the result to `output_path`.

    Entities without bboxes (or with `can_map_to_image_coordinates=False`)
    are silently skipped — the QA gate is responsible for blocking export
    when unmappable PII exists.
    """
    src = Path(source_image)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(src) as img:
        rgb = img.convert("RGB")
    draw = ImageDraw.Draw(rgb)

    width, height = rgb.size
    for entity in entities_with_bboxes:
        if not entity.bbox:
            continue
        if not entity.can_map_to_image_coordinates:
            continue
        x0, y0, x1, y1 = entity.bbox
        # Expand and clamp to image bounds.
        ex0 = max(0, int(x0) - expand_px)
        ey0 = max(0, int(y0) - expand_px)
        ex1 = min(width, int(x1) + expand_px)
        ey1 = min(height, int(y1) + expand_px)
        if ex1 <= ex0 or ey1 <= ey0:
            continue
        draw.rectangle([ex0, ey0, ex1, ey1], fill=fill)

    rgb.save(out, format="PNG")
    return out
