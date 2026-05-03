"""License-plate recognizer (label-anchored to prefer recall over precision without flooding FPs)."""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "LICENSE_PLATE"
DETECTION_REASON = "regex_license_plate_contextual"
DEFAULT_CONFIDENCE = 0.8

PATTERN = re.compile(
    r"(?i:license\s+plate|plate\s+number|plate|tag\s+number|tag)"
    r"\s*[:#\-]?\s*"
    r"([A-Z0-9][A-Z0-9-]{2,8})"
)


def find(text: str) -> list[Match]:
    return [
        Match(m.group(1), m.start(1), m.end(1), DEFAULT_CONFIDENCE)
        for m in PATTERN.finditer(text)
    ]
