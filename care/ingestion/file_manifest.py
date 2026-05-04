"""Source-file manifest entries.

Each entry records absolute path, size, SHA-256, file type, and discovery
time. Manifests are JSON-serializable through `dataclasses.asdict`.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .hashing import sha256_file
from .supported_files import is_image, is_pdf


@dataclass(frozen=True)
class FileEntry:
    path: str
    name: str
    size_bytes: int
    sha256: str
    file_type: str  # "pdf" | "image"
    extension: str
    discovered_at: str  # ISO-8601 UTC

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _classify(path: Path) -> str:
    if is_pdf(path):
        return "pdf"
    if is_image(path):
        return "image"
    return "unknown"


def build_file_entry(path: Path | str) -> FileEntry:
    p = Path(path).resolve()
    if not p.is_file():
        raise FileNotFoundError(p)
    stat = p.stat()
    return FileEntry(
        path=str(p),
        name=p.name,
        size_bytes=stat.st_size,
        sha256=sha256_file(p),
        file_type=_classify(p),
        extension=p.suffix.lower(),
        discovered_at=datetime.now(UTC).isoformat(),
    )


def build_file_manifest(paths: Iterable[Path | str]) -> list[FileEntry]:
    return [build_file_entry(p) for p in paths]
