"""License-plate recognizer (label-anchored to prefer recall over precision without flooding FPs)."""
from __future__ import annotations

import re

from ._base import RegexRecognizer


class LicensePlateRecognizer(RegexRecognizer):
    entity_type = "LICENSE_PLATE"
    detection_reason = "regex_license_plate_contextual"
    default_confidence = 0.8
    capture_group = 1
    pattern = re.compile(
        r"(?i:license\s+plate|plate\s+number|plate|tag\s+number|tag)"
        r"\s*[:#\-]?\s*"
        r"([A-Z0-9][A-Z0-9-]{2,8})"
    )


find = LicensePlateRecognizer.find
