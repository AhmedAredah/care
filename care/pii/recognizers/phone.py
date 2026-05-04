"""Phone number recognizer (US-style)."""
from __future__ import annotations

import re

from ._base import RegexRecognizer


class PhoneRecognizer(RegexRecognizer):
    entity_type = "PHONE_NUMBER"
    detection_reason = "regex_phone_us"
    default_confidence = 0.85
    pattern = re.compile(
        r"\b(?:\+?1[-. ]?)?\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4}\b"
    )


find = PhoneRecognizer.find
