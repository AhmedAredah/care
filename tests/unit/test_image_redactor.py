"""Image redactor — pixel-level masking."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from care.pii.entities import PIIEntity
from care.redaction import redact_image


def _entity_at(bbox: list[float]) -> PIIEntity:
    return PIIEntity(
        entity_type="VIN",
        text="x",
        bbox=bbox,
        confidence=0.9,
        provider="regex",
        detection_reason="r:page",
        can_map_to_image_coordinates=True,
        sources=["regex"],
    )


def test_redact_image_masks_bbox_with_black(tmp_path: Path) -> None:
    src = tmp_path / "src.png"
    Image.new("RGB", (200, 100), color=(255, 255, 255)).save(src)

    out = tmp_path / "redacted.png"
    redact_image(src, [_entity_at([50.0, 20.0, 150.0, 80.0])], out, expand_px=0)

    with Image.open(out) as img:
        # Centre of the bbox must be black.
        assert img.getpixel((100, 50)) == (0, 0, 0)
        # A pixel well outside the bbox is still white.
        assert img.getpixel((10, 10)) == (255, 255, 255)


def test_redact_image_skips_entities_without_bbox(tmp_path: Path) -> None:
    src = tmp_path / "src.png"
    Image.new("RGB", (50, 50), color=(255, 255, 255)).save(src)
    no_bbox = PIIEntity(
        entity_type="VIN", text="x", confidence=0.9, provider="regex",
        sources=["regex"], can_map_to_image_coordinates=False,
    )
    out = tmp_path / "redacted.png"
    redact_image(src, [no_bbox], out)
    with Image.open(out) as img:
        # Nothing was redacted.
        assert img.getpixel((25, 25)) == (255, 255, 255)


def test_redact_image_clamps_bbox_to_image(tmp_path: Path) -> None:
    src = tmp_path / "src.png"
    Image.new("RGB", (40, 40), color=(255, 255, 255)).save(src)
    out = tmp_path / "redacted.png"
    # bbox extends past the image borders; redactor must clamp without raising.
    redact_image(
        src,
        [_entity_at([-10.0, -10.0, 1000.0, 1000.0])],
        out,
        expand_px=0,
    )
    with Image.open(out) as img:
        for x in (0, 20, 39):
            for y in (0, 20, 39):
                assert img.getpixel((x, y)) == (0, 0, 0)


def test_redact_image_skips_unmapped_entities(tmp_path: Path) -> None:
    """Entities whose can_map_to_image_coordinates is False must be silently skipped."""
    src = tmp_path / "src.png"
    Image.new("RGB", (50, 50), color=(255, 255, 255)).save(src)
    e = _entity_at([10.0, 10.0, 40.0, 40.0])
    e.can_map_to_image_coordinates = False
    out = tmp_path / "redacted.png"
    redact_image(src, [e], out, expand_px=0)
    with Image.open(out) as img:
        assert img.getpixel((25, 25)) == (255, 255, 255)
