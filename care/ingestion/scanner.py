"""Directory scanner — yields supported input files in deterministic order."""
from __future__ import annotations

from pathlib import Path

from .supported_files import is_supported


def scan_directory(directory: Path | str, *, recursive: bool = True) -> list[Path]:
    """Return all supported files under `directory`, sorted for determinism.

    Source files are never modified. Hidden files (leading dot) and unsupported
    extensions are skipped silently. Symlinks pointing outside `directory` are
    still followed but their resolved paths are returned.
    """
    root = Path(directory)
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    iterator = root.rglob("*") if recursive else root.iterdir()
    matches: list[Path] = []
    for path in iterator:
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        if not is_supported(path):
            continue
        matches.append(path)
    return sorted(matches)
