"""Driver-license number recognizer (label-anchored)."""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "DRIVER_LICENSE"
DETECTION_REASON = "regex_driver_license_contextual"
DEFAULT_CONFIDENCE = 0.85

PATTERN = re.compile(
    r"(?i:driver'?s?\s+license|D\.?L\.?)"
    r"\s*[:#\-]?\s*"
    r"([A-Z0-9][A-Z0-9-]{3,14})"
)


def find(text: str) -> list[Match]:
    return [
        Match(m.group(1), m.start(1), m.end(1), DEFAULT_CONFIDENCE)
        for m in PATTERN.finditer(text)
    ]
