"""Medical-info keyword recognizer."""
from __future__ import annotations

import re

from ._base import RegexRecognizer


class MedicalInfoRecognizer(RegexRecognizer):
    entity_type = "MEDICAL_INFO"
    detection_reason = "regex_medical_keywords"
    default_confidence = 0.6
    pattern = re.compile(
        r"\b(?:hospital|EMS|paramedic|ambulance|injury|injured|fatal|fatality|"
        r"BAC|blood\s+alcohol|toxicology|deceased|"
        r"transported\s+to|treated\s+at)\b",
        re.IGNORECASE,
    )


find = MedicalInfoRecognizer.find
