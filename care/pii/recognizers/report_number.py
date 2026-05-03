"""Report-number recognizer (label-anchored).

Label is case-insensitive; the captured value must be uppercase
alphanumerics + hyphens (case-sensitive) so that ordinary words like
``Form`` or ``Section`` appearing after a ``Report`` heading are not
falsely flagged.
"""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "REPORT_NUMBER"
DETECTION_REASON = "regex_report_number_contextual"
DEFAULT_CONFIDENCE = 0.85

PATTERN = re.compile(
    r"(?i:report(?:\s+(?:number|no\.?|#))?|incident\s+number)"
    r"\s*[:#\-]?\s*"
    r"([A-Z0-9][A-Z0-9-]{2,19})"
)


def find(text: str) -> list[Match]:
    return [
        Match(m.group(1), m.start(1), m.end(1), DEFAULT_CONFIDENCE)
        for m in PATTERN.finditer(text)
    ]
