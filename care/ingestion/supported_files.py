"""Supported input file extensions."""
from __future__ import annotations

from pathlib import Path

from ..core.constants import SUPPORTED_FILE_EXTENSIONS

_IMAGE_EXTS: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff"})
_PDF_EXTS: frozenset[str] = frozenset({".pdf"})


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_FILE_EXTENSIONS


def is_pdf(path: Path) -> bool:
    return path.suffix.lower() in _PDF_EXTS


def is_image(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_EXTS
