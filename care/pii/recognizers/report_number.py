"""Report-number recognizer (label-anchored).

Label is case-insensitive; the captured value must be uppercase
alphanumerics + hyphens (case-sensitive) so that ordinary words like
``Form`` or ``Section`` appearing after a ``Report`` heading are not
falsely flagged.
"""
from __future__ import annotations

import re

from ._base import RegexRecognizer


class ReportNumberRecognizer(RegexRecognizer):
    entity_type = "REPORT_NUMBER"
    detection_reason = "regex_report_number_contextual"
    default_confidence = 0.85
    capture_group = 1
    pattern = re.compile(
        r"(?i:report(?:\s+(?:number|no\.?|#))?|incident\s+number)"
        r"\s*[:#\-]?\s*"
        r"([A-Z0-9][A-Z0-9-]{2,19})"
    )


find = ReportNumberRecognizer.find
