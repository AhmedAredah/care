"""Case-number recognizer (label-anchored).

Label is case-insensitive; the captured value is uppercase only so that
ordinary words after a ``Case`` heading aren't falsely flagged.
"""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "CASE_NUMBER"
DETECTION_REASON = "regex_case_number_contextual"
DEFAULT_CONFIDENCE = 0.85

PATTERN = re.compile(
    r"(?i:case(?:\s+(?:number|no\.?|#))?)"
    r"\s*[:#\-]?\s*"
    r"([A-Z0-9][A-Z0-9-]{2,19})"
)


def find(text: str) -> list[Match]:
    return [
        Match(m.group(1), m.start(1), m.end(1), DEFAULT_CONFIDENCE)
        for m in PATTERN.finditer(text)
    ]
