"""Date-of-birth recognizer (label-anchored — incident dates are intentionally NOT matched)."""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "DATE_OF_BIRTH"
DETECTION_REASON = "regex_dob_contextual"
DEFAULT_CONFIDENCE = 0.85

PATTERN = re.compile(
    r"(?:DOB|D\.O\.B\.|date\s+of\s+birth|born)\s*[:\-]?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
    re.IGNORECASE,
)


def find(text: str) -> list[Match]:
    return [
        Match(m.group(1), m.start(1), m.end(1), DEFAULT_CONFIDENCE)
        for m in PATTERN.finditer(text)
    ]
