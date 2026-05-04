"""Email recognizer."""
from __future__ import annotations

import re

from ._base import RegexRecognizer


class EmailRecognizer(RegexRecognizer):
    entity_type = "EMAIL"
    detection_reason = "regex_email"
    default_confidence = 0.95
    pattern = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


find = EmailRecognizer.find
