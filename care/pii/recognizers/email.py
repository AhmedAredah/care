"""Email recognizer."""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "EMAIL"
DETECTION_REASON = "regex_email"
DEFAULT_CONFIDENCE = 0.95

PATTERN = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def find(text: str) -> list[Match]:
    return [
        Match(m.group(0), m.start(), m.end(), DEFAULT_CONFIDENCE)
        for m in PATTERN.finditer(text)
    ]
