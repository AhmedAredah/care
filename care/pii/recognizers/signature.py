"""Signature-label recognizer.

Phase 4 detects signatures only in *text* form — the visual signature
classifier (image-side) is not in scope. Recall-prioritised: any
"signature: <text>" or "signed by <text>" gets flagged.
"""
from __future__ import annotations

import re

from ._base import Match, RegexRecognizer


class SignatureRecognizer(RegexRecognizer):
    entity_type = "SIGNATURE"
    detection_reason = "regex_signature_label"
    default_confidence = 0.6
    capture_group = 1
    pattern = re.compile(
        r"(?i:signature|signed\s+by)"
        r"\s*[:\-]\s*"
        r"([A-Z][a-zA-Z'\.\s]{2,40})"
    )

    @classmethod
    def find(cls, text: str) -> list[Match]:
        # The captured group can include trailing whitespace before the
        # next sentence (the regex deliberately allows internal spaces
        # to capture multi-word names like "J. Smith"); rstrip and
        # contract the span to the trimmed length so the offsets stay
        # accurate.
        out: list[Match] = []
        for m in cls.pattern.finditer(text):
            captured = m.group(1)
            trimmed = captured.rstrip()
            start = m.start(1)
            end = start + len(trimmed)
            out.append(Match(trimmed, start, end, cls.default_confidence))
        return out


find = SignatureRecognizer.find
