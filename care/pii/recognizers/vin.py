"""VIN recognizer (ISO 3779 — 17 chars, no I/O/Q)."""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "VIN"
DETECTION_REASON = "regex_vin_iso3779"
DEFAULT_CONFIDENCE = 0.92

PATTERN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")


def find(text: str) -> list[Match]:
    return [
        Match(m.group(0), m.start(), m.end(), DEFAULT_CONFIDENCE)
        for m in PATTERN.finditer(text)
    ]
