"""Phone number recognizer (US-style)."""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "PHONE_NUMBER"
DETECTION_REASON = "regex_phone_us"
DEFAULT_CONFIDENCE = 0.85

PATTERN = re.compile(
    r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b"
)


def find(text: str) -> list[Match]:
    return [
        Match(m.group(0), m.start(), m.end(), DEFAULT_CONFIDENCE)
        for m in PATTERN.finditer(text)
    ]
