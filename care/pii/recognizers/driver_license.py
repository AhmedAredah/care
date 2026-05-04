"""Driver-license number recognizer (label-anchored)."""
from __future__ import annotations

import re

from ._base import RegexRecognizer


class DriverLicenseRecognizer(RegexRecognizer):
    entity_type = "DRIVER_LICENSE"
    detection_reason = "regex_driver_license_contextual"
    default_confidence = 0.85
    capture_group = 1
    pattern = re.compile(
        r"(?i:driver'?s?\s+license|D\.?L\.?)"
        r"\s*[:#\-]?\s*"
        r"([A-Z0-9][A-Z0-9-]{3,14})"
    )


find = DriverLicenseRecognizer.find
