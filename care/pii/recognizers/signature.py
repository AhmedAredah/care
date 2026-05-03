"""Signature-label recognizer.

Phase 4 detects signatures only in *text* form — the visual signature
classifier (image-side) is not in scope. Recall-prioritised: any
"signature: <text>" or "signed by <text>" gets flagged.
"""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "SIGNATURE"
DETECTION_REASON = "regex_signature_label"
DEFAULT_CONFIDENCE = 0.6

PATTERN = re.compile(
    r"(?i:signature|signed\s+by)"
    r"\s*[:\-]\s*"
    r"([A-Z][a-zA-Z'\.\s]{2,40})"
)


def find(text: str) -> list[Match]:
    return [
        Match(m.group(1).rstrip(), m.start(1), m.start(1) + len(m.group(1).rstrip()), DEFAULT_CONFIDENCE)
        for m in PATTERN.finditer(text)
    ]
