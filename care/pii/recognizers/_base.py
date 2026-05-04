"""Shared types and base class for crash-report-specific PII recognizers.

Every recognizer is a subclass of :class:`RegexRecognizer` that
declares four class attributes — ``entity_type``, ``detection_reason``,
``default_confidence``, ``pattern`` — and inherits ``find()``.
Recognizers that need extra validation (VIN check digit, DOB calendar
plausibility) override :meth:`is_valid`. Recognizers with a fundamentally
different shape (signature whitespace trim, person_name's two-pattern
union) override :meth:`find` outright.

Each recognizer module also exposes a module-level ``find`` callable
that aliases the class's classmethod so call-sites like
``vin.find(text)`` keep working without instantiating a class.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Match:
    text: str
    start: int
    end: int
    confidence: float = 0.85


class RegexRecognizer:
    """Base class for regex-driven PII recognizers.

    Subclasses set the four class attributes below and inherit
    ``find()``. Override :meth:`is_valid` to filter false positives
    that the regex matched but a domain check rejects (e.g., VIN
    check digit, calendar-impossible DOBs). Override :meth:`find`
    when the recognizer needs more than one pattern or has to
    post-process the captured span.
    """

    entity_type: str = ""
    detection_reason: str = ""
    default_confidence: float = 0.85
    pattern: re.Pattern[str]
    # 0 = full match (the regex has no capture group, or the full match
    # IS the value). 1 = first capture group (label-anchored patterns
    # where the capture is the value and the prefix is just an anchor).
    capture_group: int = 0

    @classmethod
    def find(cls, text: str) -> list[Match]:
        out: list[Match] = []
        group = cls.capture_group
        for m in cls.pattern.finditer(text):
            value = m.group(group)
            if not cls.is_valid(value):
                continue
            out.append(Match(value, m.start(group), m.end(group), cls.default_confidence))
        return out

    @classmethod
    def is_valid(cls, value: str) -> bool:
        """Hook for post-regex domain validation. Default: accept anything
        the pattern matched. Override to reject false positives."""
        return True
