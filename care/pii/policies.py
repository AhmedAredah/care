"""Default DOT redaction policy: placeholder mapping + bbox expansion."""
from __future__ import annotations

PLACEHOLDERS: dict[str, str] = {
    "PERSON_NAME": "[PERSON_NAME]",
    "ADDRESS": "[ADDRESS]",
    "PHONE_NUMBER": "[PHONE_NUMBER]",
    "EMAIL": "[EMAIL]",
    "DATE_OF_BIRTH": "[DATE_OF_BIRTH]",
    "DRIVER_LICENSE": "[DRIVER_LICENSE]",
    "LICENSE_PLATE": "[LICENSE_PLATE]",
    "VIN": "[VIN]",
    "INSURANCE_POLICY": "[INSURANCE_POLICY]",
    "CASE_NUMBER": "[CASE_NUMBER]",
    "REPORT_NUMBER": "[REPORT_NUMBER]",
    "SIGNATURE": "[SIGNATURE]",
    "MEDICAL_INFO": "[MEDICAL_INFO]",
    "WITNESS_INFO": "[WITNESS_INFO]",
    "VEHICLE_OWNER_INFO": "[VEHICLE_OWNER_INFO]",
    "SSN": "[SSN]",
    "VEHICLE_REGISTRATION": "[VEHICLE_REGISTRATION]",
    "FULL_FACE_IMAGE": "[FULL_FACE_IMAGE]",
}

REDACTION_POLICY_NAME = "dot_default_v1"

# Pixels of padding to add around image-redaction boxes to swallow OCR
# coordinate uncertainty (CONTRACT §PII Redaction Interface).
DEFAULT_BBOX_EXPANSION_PX = 4


def placeholder_for(entity_type: str) -> str:
    return PLACEHOLDERS.get(entity_type, f"[{entity_type}]")
