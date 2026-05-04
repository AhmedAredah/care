"""Aggregate confidence helpers."""
from __future__ import annotations

from ..document_ir.models import DocumentIR


def average_word_confidence(document_ir: DocumentIR) -> float | None:
    """Average non-None word confidences across the entire document."""
    confidences = [
        word.confidence
        for page in document_ir.pages
        for word in page.words
        if word.confidence is not None
    ]
    if not confidences:
        return None
    return sum(confidences) / len(confidences)
