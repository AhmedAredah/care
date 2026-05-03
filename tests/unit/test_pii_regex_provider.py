"""Regex PII provider end-to-end behavior."""
from __future__ import annotations

from care.pii.providers.regex_provider import RegexPIIProvider


def test_regex_provider_loads_and_supports_documented_entities() -> None:
    p = RegexPIIProvider()
    p.load({})
    expected = {
        "VIN", "PHONE_NUMBER", "EMAIL", "ADDRESS",
        "DATE_OF_BIRTH", "DRIVER_LICENSE", "LICENSE_PLATE",
        "INSURANCE_POLICY", "REPORT_NUMBER", "CASE_NUMBER",
        "PERSON_NAME", "SIGNATURE", "MEDICAL_INFO",
    }
    assert expected.issubset(set(p.supported_entities))


def test_regex_provider_finds_pii_in_synthetic_text() -> None:
    p = RegexPIIProvider()
    p.load({})
    text = (
        "Driver JANE DOE phone 555-123-4567 email j@e.co "
        "VIN 1HGCM82633A004352 DOB: 01/02/1990 Officer Smith"
    )
    entities = p.detect_text(text, context={"page_index": 0, "scope": "page"})
    types = {e.entity_type for e in entities}
    assert {"PERSON_NAME", "PHONE_NUMBER", "EMAIL", "VIN", "DATE_OF_BIRTH"}.issubset(types)
    for e in entities:
        assert e.provider == "regex"
        assert e.detection_reason.endswith(":page")
        assert e.page_index == 0
        assert e.sources == ["regex"]


def test_regex_provider_reports_recall_priority_in_manifest() -> None:
    p = RegexPIIProvider()
    p.load({})
    manifest = p.get_model_manifest()
    assert manifest["recall_priority"] is True
    assert manifest["requires_network"] is False
    assert manifest["enabled_by_default"] is True


def test_regex_provider_healthcheck_after_load() -> None:
    p = RegexPIIProvider()
    assert p.healthcheck().healthy is False
    p.load({})
    assert p.healthcheck().healthy is True
