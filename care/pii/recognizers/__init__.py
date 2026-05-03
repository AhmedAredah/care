"""Crash-report-specific PII recognizers."""
from __future__ import annotations

from types import ModuleType

from . import (
    address,
    case_number,
    date_of_birth,
    driver_license,
    email,
    insurance_policy,
    license_plate,
    medical_info,
    person_name,
    phone,
    report_number,
    signature,
    vin,
)
from ._base import Match

ALL_RECOGNIZERS: tuple[ModuleType, ...] = (
    vin,
    license_plate,
    driver_license,
    phone,
    email,
    address,
    date_of_birth,
    report_number,
    case_number,
    insurance_policy,
    person_name,
    signature,
    medical_info,
)

__all__ = [
    "ALL_RECOGNIZERS",
    "Match",
    "address",
    "case_number",
    "date_of_birth",
    "driver_license",
    "email",
    "insurance_policy",
    "license_plate",
    "medical_info",
    "person_name",
    "phone",
    "report_number",
    "signature",
    "vin",
]
