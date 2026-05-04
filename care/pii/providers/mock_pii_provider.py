"""Deterministic mock PII provider used by tests.

Detects a small set of clearly-synthetic patterns. Real recognizers
land in Phase 4.
"""
from __future__ import annotations

import re
from typing import Any

from ...ocr.base import ProviderHealth
from ..base import PIIDetectionProvider
from ..entities import PIIEntity

_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("PHONE_NUMBER", re.compile(r"\b\d{3}[-. ]?\d{3}[-. ]?\d{4}\b"), "regex_phone_us"),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "regex_email"),
    ("VIN", re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b"), "regex_vin"),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "regex_ssn"),
    ("PERSON_NAME", re.compile(r"\b(JOHN|JANE)\s+DOE\b", re.IGNORECASE), "regex_synthetic_name"),
]


class MockPIIProvider(PIIDetectionProvider):
    name = "mock_pii"
    version = "0.1.0"
    provider_type = "pii_detector"
    requires_network = False
    enabled_by_default = False

    supported_entities = ["PHONE_NUMBER", "EMAIL", "VIN", "SSN", "PERSON_NAME"]
    supports_offsets = True
    supports_bboxes = False
    supports_confidence = False

    def __init__(self) -> None:
        self._loaded = False

    def load(self, config: dict[str, Any]) -> None:
        self._loaded = True

    def detect_text(self, text: str, context: dict[str, Any] | None = None) -> list[PIIEntity]:
        results: list[PIIEntity] = []
        for entity_type, pattern, reason in _PATTERNS:
            for match in pattern.finditer(text):
                results.append(
                    PIIEntity(
                        entity_type=entity_type,
                        text=match.group(0),
                        start_offset=match.start(),
                        end_offset=match.end(),
                        confidence=0.9,
                        provider=self.name,
                        detection_reason=reason,
                        can_map_to_image_coordinates=False,
                        requires_review=False,
                        sources=[self.name],
                    )
                )
        return results

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=self._loaded, detail="mock loaded" if self._loaded else "not loaded")

    def get_model_manifest(self) -> dict[str, Any]:
        return {
            "provider_name": self.name,
            "provider_version": self.version,
            "provider_type": self.provider_type,
            "model_name": "mock",
            "model_version": self.version,
            "model_path": None,
            "model_checksums": {},
            "license": "Apache-2.0",
            "requires_network": self.requires_network,
            "enabled_by_default": self.enabled_by_default,
            "safe_for_offline_use": True,
            "supported_entities": list(self.supported_entities),
        }
