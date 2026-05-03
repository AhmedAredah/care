"""Common helpers for normalized-bbox → pixel conversion."""
from __future__ import annotations

from typing import Optional


def bbox_norm_to_pixels(
    bbox_norm: list[float] | tuple[float, float, float, float],
    image_width: int,
    image_height: int,
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bbox_norm
    return (
        max(0, int(x0 * image_width)),
        max(0, int(y0 * image_height)),
        min(image_width, int(x1 * image_width)),
        min(image_height, int(y1 * image_height)),
    )


def is_valid_bbox_norm(bbox_norm: Optional[list[float] | tuple[float, ...]]) -> bool:
    if bbox_norm is None or len(bbox_norm) != 4:
        return False
    x0, y0, x1, y1 = bbox_norm
    return 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
