"""Helpers to synthesize PDF and image fixtures at test time.

All fixtures are clearly synthetic — no real DOT data, no real PII.
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF
from PIL import Image, ImageDraw


def make_synthetic_image(
    path: Path,
    *,
    size: tuple[int, int] = (800, 1000),
    label: str = "SYNTHETIC IMAGE",
) -> Path:
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), label, fill="black")
    img.save(path, format="PNG")
    return path


def make_digital_pdf(path: Path, *, lines: list[str] | None = None) -> Path:
    """Synthesize a PDF with a real native text layer."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in lines or [
        "MOCK CRASH REPORT",
        "Officer Synthetic Test Only",
        "Narrative: synthetic content for tests.",
    ]:
        pdf.cell(0, 10, line)
        pdf.ln()
    pdf.output(str(path))
    return path


def make_image_only_pdf(path: Path, *, image_path: Path) -> Path:
    """Synthesize a PDF with no text layer, only a rasterized image."""
    pdf = FPDF()
    pdf.add_page()
    pdf.image(str(image_path), x=10, y=10, w=180)
    pdf.output(str(path))
    return path


def make_example_template_pdf(
    path: Path,
    *,
    narrative_body: str = "Vehicle A was traveling north when Vehicle B made an unsafe lane change.",
    form_number: str = "EX-CR-12345",
    officer_line: str = "Officer",
) -> Path:
    """Synthesize a PDF whose text layer matches the example_template_v1 anchors.

    The default narrative carries no PII shapes — useful for tests that
    want `qa.export_decision == "ALLOW"` on the native-text path. The
    last line defaults to bare ``Officer`` so the narrative anchor closes
    cleanly without introducing a person name into the page.
    """
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in [
        "Example Crash Report",
        f"Form: {form_number}",
        "Diagram",
        "Narrative",
        narrative_body,
        officer_line,
    ]:
        pdf.cell(0, 10, line)
        pdf.ln()
    pdf.output(str(path))
    return path


def make_unknown_template_pdf(path: Path) -> Path:
    """A digital PDF whose text matches no registered template."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)
    for line in [
        "Random Document Title",
        "This text contains no template anchors.",
        "Lorem ipsum dolor sit amet.",
    ]:
        pdf.cell(0, 10, line)
        pdf.ln()
    pdf.output(str(path))
    return path
