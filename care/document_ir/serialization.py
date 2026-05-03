"""DocumentIR ↔ JSON helpers."""
from __future__ import annotations

from .models import DocumentIR


def to_json(doc: DocumentIR, indent: int | None = 2) -> str:
    return doc.model_dump_json(indent=indent)


def from_json(payload: str) -> DocumentIR:
    return DocumentIR.model_validate_json(payload)
