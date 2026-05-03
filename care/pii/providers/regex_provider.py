"""Default regex-based PII detector.

Wires every recognizer in `care/pii/recognizers/` and emits
PIIEntity instances. Recall-prioritised: false positives are acceptable;
false negatives are dangerous.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ...ocr.base import ProviderHealth
from ..base import PIIDetectionProvider
from ..entities import PIIEntity
from ..recognizers import ALL_RECOGNIZERS


def _load_accuracy() -> Optional[dict[str, Any]]:
    """Read the Tier-A benchmark result committed alongside this module.

    Re-run ``scripts/bench/run_pii_bench.py`` against the synthetic
    corpus to refresh the file. Fail-soft to ``None`` so a missing
    file (e.g., a partial source checkout) doesn't break import.
    """
    path = Path(__file__).with_name("regex_accuracy.json")
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


class RegexPIIProvider(PIIDetectionProvider):
    name = "regex"
    version = "0.1.0"
    provider_type = "pii_detector"
    requires_network = False
    enabled_by_default = True

    supported_entities = sorted({r.ENTITY_TYPE for r in ALL_RECOGNIZERS})
    supports_offsets = True
    supports_bboxes = False
    supports_confidence = True

    accuracy_metrics = _load_accuracy()

    def __init__(self) -> None:
        self._loaded = False

    def load(self, config: dict[str, Any]) -> None:
        self._loaded = True

    def detect_text(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> list[PIIEntity]:
        results: list[PIIEntity] = []
        page_index = (context or {}).get("page_index")
        scope = (context or {}).get("scope", "page")
        for recognizer in ALL_RECOGNIZERS:
            for match in recognizer.find(text):
                results.append(
                    PIIEntity(
                        entity_type=recognizer.ENTITY_TYPE,
                        text=match.text,
                        start_offset=match.start,
                        end_offset=match.end,
                        page_index=page_index,
                        confidence=match.confidence,
                        provider=self.name,
                        detection_reason=f"{recognizer.DETECTION_REASON}:{scope}",
                        can_map_to_image_coordinates=False,
                        requires_review=False,
                        sources=[self.name],
                    )
                )
        return results

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=self._loaded,
            detail=f"{len(ALL_RECOGNIZERS)} recognizers loaded" if self._loaded else "not loaded",
        )

    def get_model_manifest(self) -> dict[str, Any]:
        return {
            "provider_name": self.name,
            "provider_version": self.version,
            "provider_type": self.provider_type,
            "model_name": "regex-rules",
            "model_version": self.version,
            "model_path": None,
            "model_checksums": {},
            "license": "Apache-2.0",
            "requires_network": False,
            "enabled_by_default": self.enabled_by_default,
            "safe_for_offline_use": True,
            "supported_entities": list(self.supported_entities),
            "recall_priority": True,
        }
