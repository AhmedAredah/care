"""Case-number recognizer (label-anchored).

Label is case-insensitive; the captured value is uppercase only so that
ordinary words after a ``Case`` heading aren't falsely flagged.
"""
from __future__ import annotations

import re

from ._base import RegexRecognizer


class CaseNumberRecognizer(RegexRecognizer):
    entity_type = "CASE_NUMBER"
    detection_reason = "regex_case_number_contextual"
    default_confidence = 0.85
    capture_group = 1
    pattern = re.compile(
        r"(?i:case(?:\s+(?:number|no\.?|#))?)"
        r"\s*[:#\-]?\s*"
        r"([A-Z0-9][A-Z0-9-]{2,19})"
    )


find = CaseNumberRecognizer.find
