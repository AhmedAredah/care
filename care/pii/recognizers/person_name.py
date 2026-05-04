"""Person-name recognizer (label-anchored).

Captures the name portion that follows one of a fixed set of role
keywords typical of crash-report narrative — *Officer Smith*,
*Driver Johnson*, *Witness named Jane Lee*. The role anchor is
case-insensitive so the recognizer fires on both prose ("the witness
named …") and ALL-CAPS form fields ("DRIVER …").

Names without an anchoring role keyword are intentionally not matched
here. Regex doesn't have a good answer for general name detection —
that's what the NER providers (RoBERTa-NER, Piiranha) are for. This
recognizer is a deterministic, no-model best-effort layer for the
cases that *do* follow a regular shape; operators who need broader
name coverage should add an NER provider to ``pii.provider_chain``.
"""
from __future__ import annotations

import re

from ._base import RegexRecognizer


class PersonNameRecognizer(RegexRecognizer):
    entity_type = "PERSON_NAME"
    detection_reason = "regex_person_name"
    default_confidence = 0.7
    capture_group = 1
    pattern = re.compile(
        r"(?i:officer|driver|witness|owner|operator|patient|pedestrian|"
        r"suspect|victim|named)\s+"
        r"([A-Z][a-zA-Z'\.]{1,30}(?:\s+[A-Z][a-zA-Z'\.]{1,30}){0,3})\b"
    )


find = PersonNameRecognizer.find
