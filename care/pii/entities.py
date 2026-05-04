"""PII entity dataclass and the canonical entity-type vocabulary."""
from __future__ import annotations

from dataclasses import dataclass, field

# Canonical entity types. The redaction layer maps these to placeholder
# strings (Phase 4). Detectors are free to return additional types but
# everything in this set must be detectable by the default chain.
ENTITY_TYPES: frozenset[str] = frozenset({
    "PERSON_NAME",
    "ADDRESS",
    "PHONE_NUMBER",
    "EMAIL",
    "DATE_OF_BIRTH",
    "DRIVER_LICENSE",
    "LICENSE_PLATE",
    "VIN",
    "INSURANCE_POLICY",
    "CASE_NUMBER",
    "REPORT_NUMBER",
    "SIGNATURE",
    "MEDICAL_INFO",
    "WITNESS_INFO",
    "VEHICLE_OWNER_INFO",
    "SSN",
    "VEHICLE_REGISTRATION",
    "FULL_FACE_IMAGE",
})


@dataclass
class PIIEntity:
    entity_type: str
    text: str
    normalized_text: str | None = None
    start_offset: int | None = None
    end_offset: int | None = None
    page_index: int | None = None
    bbox: list[float] | None = None
    confidence: float = 1.0
    provider: str = ""
    detection_reason: str = ""
    can_map_to_image_coordinates: bool = False
    requires_review: bool = False
    sources: list[str] = field(default_factory=list)
