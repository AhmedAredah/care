"""Diagram extractor behavior."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from care.document_ir import DocumentIR, Page
from care.extraction import extract_diagram
from care.templates import TemplateSchema


def _template_with_diagram(bbox=None) -> TemplateSchema:
    return TemplateSchema.model_validate(
        {
            "template_id": "t",
            "regions": {
                "diagram": {
                    "page": 0,
                    "bbox_norm": bbox or [0.1, 0.1, 0.9, 0.5],
                    "requires_redaction": True,
                }
            },
        }
    )


def _doc(pages: int = 1, width: int = 800, height: int = 1000) -> DocumentIR:
    return DocumentIR(
        document_id="d",
        source_file_name="x.pdf",
        source_sha256="0" * 64,
        file_type="pdf",
        created_at="2026-05-01T00:00:00Z",
        pages=[Page(page_index=i, width=width, height=height) for i in range(pages)],
    )


def _make_image(path: Path, size=(800, 1000)) -> Path:
    Image.new("RGB", size, color="white").save(path, format="PNG")
    return path


def test_extract_diagram_returns_none_when_no_region(tmp_path: Path) -> None:
    template = TemplateSchema.model_validate({"template_id": "t"})
    result = extract_diagram(template, _doc(), work_dir=tmp_path, source_image_paths={})
    assert result is None


def test_extract_diagram_crops_when_image_available(tmp_path: Path) -> None:
    page_image = _make_image(tmp_path / "page_0.png", size=(800, 1000))
    result = extract_diagram(
        _template_with_diagram(),
        _doc(),
        work_dir=tmp_path / "out",
        source_image_paths={0: page_image},
    )
    assert result is not None
    assert result.image_path is not None
    assert Path(result.image_path).exists()
    assert result.bbox_norm == (0.1, 0.1, 0.9, 0.5)
    assert result.bbox_pixels == (80, 100, 720, 500)
    assert result.confidence >= 0.85
    assert result.requires_review is False
    assert result.warnings == []
    # The crop file dimensions match the bbox.
    with Image.open(result.image_path) as cropped:
        assert cropped.size == (720 - 80, 500 - 100)


def test_extract_diagram_without_rendered_image_flags_uncertain(tmp_path: Path) -> None:
    result = extract_diagram(
        _template_with_diagram(),
        _doc(),
        work_dir=tmp_path,
        source_image_paths={},
    )
    assert result is not None
    assert result.image_path is None
    assert result.requires_review is True
    assert "DIAGRAM_REGION_UNCERTAIN" in result.warnings
    assert result.confidence < 0.7


def test_extract_diagram_out_of_bounds_page_returns_review(tmp_path: Path) -> None:
    template = _template_with_diagram()
    # Single-page document but template targets page 0; flip to nonexistent page.
    template = TemplateSchema.model_validate(
        {
            "template_id": "t",
            "regions": {
                "diagram": {
                    "page": 5,
                    "bbox_norm": [0.1, 0.1, 0.9, 0.5],
                }
            },
        }
    )
    result = extract_diagram(template, _doc(pages=1), work_dir=tmp_path, source_image_paths={})
    assert result is not None
    assert result.requires_review is True
    assert "DIAGRAM_REGION_OUT_OF_BOUNDS" in result.warnings
