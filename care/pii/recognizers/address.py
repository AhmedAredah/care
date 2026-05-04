"""US street-address recognizer (number + name + street suffix)."""
from __future__ import annotations

import re

from ._base import RegexRecognizer


class AddressRecognizer(RegexRecognizer):
    entity_type = "ADDRESS"
    detection_reason = "regex_us_street_address"
    default_confidence = 0.7
    # Examples matched: "123 Main St", "4567 Oak Avenue", "9 W. Elm Road".
    pattern = re.compile(
        r"\b\d{1,5}\s+(?:[NSEW]\.?\s+)?[A-Za-z][\w\.]{1,30}(?:\s+[A-Za-z][\w\.]{0,20}){0,3}\s+"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Way|Court|Ct|Place|Pl|Highway|Hwy|Parkway|Pkwy|Trail|Trl)\b\.?",
        re.IGNORECASE,
    )


find = AddressRecognizer.find
