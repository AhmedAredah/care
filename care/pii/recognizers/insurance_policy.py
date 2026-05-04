"""Insurance-policy-number recognizer (label-anchored)."""
from __future__ import annotations

import re

from ._base import RegexRecognizer


class InsurancePolicyRecognizer(RegexRecognizer):
    entity_type = "INSURANCE_POLICY"
    detection_reason = "regex_insurance_policy_contextual"
    default_confidence = 0.85
    capture_group = 1
    pattern = re.compile(
        r"(?i:insurance\s+policy|policy(?:\s+number|\s+no\.?|\s+#)?)"
        r"\s*[:#\-]?\s*"
        r"([A-Z0-9][A-Z0-9-]{3,19})"
    )


find = InsurancePolicyRecognizer.find
