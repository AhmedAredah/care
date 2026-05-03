"""Medical-info keyword recognizer."""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "MEDICAL_INFO"
DETECTION_REASON = "regex_medical_keywords"
DEFAULT_CONFIDENCE = 0.6

PATTERN = re.compile(
    r"\b(?:hospital|EMS|paramedic|ambulance|injury|injured|fatal|fatality|"
    r"BAC|blood\s+alcohol|toxicology|deceased|"
    r"transported\s+to|treated\s+at)\b",
    re.IGNORECASE,
)


def find(text: str) -> list[Match]:
    return [
        Match(m.group(0), m.start(), m.end(), DEFAULT_CONFIDENCE)
        for m in PATTERN.finditer(text)
    ]
