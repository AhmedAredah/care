"""Crash-report-specific PII recognizers."""
from __future__ import annotations

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
from ._base import Match, RegexRecognizer
from .address import AddressRecognizer
from .case_number import CaseNumberRecognizer
from .date_of_birth import DateOfBirthRecognizer
from .driver_license import DriverLicenseRecognizer
from .email import EmailRecognizer
from .insurance_policy import InsurancePolicyRecognizer
from .license_plate import LicensePlateRecognizer
from .medical_info import MedicalInfoRecognizer
from .person_name import PersonNameRecognizer
from .phone import PhoneRecognizer
from .report_number import ReportNumberRecognizer
from .signature import SignatureRecognizer
from .vin import VinRecognizer

ALL_RECOGNIZERS: tuple[type[RegexRecognizer], ...] = (
    VinRecognizer,
    LicensePlateRecognizer,
    DriverLicenseRecognizer,
    PhoneRecognizer,
    EmailRecognizer,
    AddressRecognizer,
    DateOfBirthRecognizer,
    ReportNumberRecognizer,
    CaseNumberRecognizer,
    InsurancePolicyRecognizer,
    PersonNameRecognizer,
    SignatureRecognizer,
    MedicalInfoRecognizer,
)

__all__ = [
    "ALL_RECOGNIZERS",
    "Match",
    "RegexRecognizer",
    "AddressRecognizer",
    "CaseNumberRecognizer",
    "DateOfBirthRecognizer",
    "DriverLicenseRecognizer",
    "EmailRecognizer",
    "InsurancePolicyRecognizer",
    "LicensePlateRecognizer",
    "MedicalInfoRecognizer",
    "PersonNameRecognizer",
    "PhoneRecognizer",
    "ReportNumberRecognizer",
    "SignatureRecognizer",
    "VinRecognizer",
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
