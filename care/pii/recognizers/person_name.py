"""Person-name recognizer.

Two patterns combined: a label-anchored matcher that captures the
name portion after role keywords (Officer / Driver / ...), and a
synthetic-fixture matcher for ``JOHN DOE``-style placeholders used in
tests. Each pattern carries its own confidence.
"""
from __future__ import annotations

import re

from ._base import Match, RegexRecognizer


class PersonNameRecognizer(RegexRecognizer):
    entity_type = "PERSON_NAME"
    detection_reason = "regex_person_name"
    default_confidence = 0.7
    # ``pattern`` here is the contextual one so generic introspection
    # (e.g., bench tools that read ``cls.pattern``) sees the primary
    # matcher; ``find`` runs both.
    pattern = re.compile(
        r"(?:Officer|Driver|Witness|Owner|Operator|Patient|Pedestrian|Suspect|Victim)\s+"
        r"([A-Z][a-zA-Z'\.]{1,30}(?:\s+[A-Z][a-zA-Z'\.]{1,30}){0,3})\b"
    )

    _SYNTHETIC_PATTERN = re.compile(r"\b(?:JOHN|JANE)\s+DOE\b", re.IGNORECASE)
    _SYNTHETIC_CONFIDENCE = 0.95

    @classmethod
    def find(cls, text: str) -> list[Match]:
        matches: list[Match] = []
        for m in cls.pattern.finditer(text):
            matches.append(
                Match(m.group(1), m.start(1), m.end(1), cls.default_confidence)
            )
        for m in cls._SYNTHETIC_PATTERN.finditer(text):
            matches.append(
                Match(m.group(0), m.start(0), m.end(0), cls._SYNTHETIC_CONFIDENCE)
            )
        return matches


find = PersonNameRecognizer.find
