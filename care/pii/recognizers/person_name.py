"""Person-name recognizer.

Two patterns: a label-anchored matcher that captures the name portion
after role keywords (Officer/Driver/...), and a synthetic-fixture matcher
for `JOHN DOE`-style placeholders used in tests.
"""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "PERSON_NAME"
DETECTION_REASON = "regex_person_name"
DEFAULT_CONFIDENCE = 0.7

# "Officer Smith", "Driver John A. Smith", "Witness Jane Lee"
PATTERN_CONTEXTUAL = re.compile(
    r"(?:Officer|Driver|Witness|Owner|Operator|Patient|Pedestrian|Suspect|Victim)\s+"
    r"([A-Z][a-zA-Z'\.]{1,30}(?:\s+[A-Z][a-zA-Z'\.]{1,30}){0,3})\b"
)

# Synthetic fixture stand-in.
PATTERN_SYNTHETIC = re.compile(r"\b(?:JOHN|JANE)\s+DOE\b", re.IGNORECASE)


def find(text: str) -> list[Match]:
    matches: list[Match] = []
    for m in PATTERN_CONTEXTUAL.finditer(text):
        matches.append(Match(m.group(1), m.start(1), m.end(1), DEFAULT_CONFIDENCE))
    for m in PATTERN_SYNTHETIC.finditer(text):
        matches.append(Match(m.group(0), m.start(0), m.end(0), 0.95))
    return matches
