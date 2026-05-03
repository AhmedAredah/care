"""No-op OCR provider — used when a PDF already has a usable native text layer."""
from __future__ import annotations

from typing import Any

from ..base import OCRProvider, ProviderHealth
from ..result import OCRResult


class NoopOCRProvider(OCRProvider):
    name = "noop"
    version = "0.1.0"
    provider_type = "traditional_ocr"
    requires_network = False
    enabled_by_default = False

    supports_pdf = False
    supports_image = True
    supports_word_bboxes = False
    supports_line_bboxes = False
    supports_confidence = False

    def load(self, config: dict[str, Any]) -> None:
        return None

    def process_page_image(self, image: Any, page_context: dict[str, Any]) -> OCRResult:
        return OCRResult(
            provider_name=self.name,
            provider_version=self.version,
            can_map_to_image_coordinates=False,
        )

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True, detail="noop")

    def get_model_manifest(self) -> dict[str, Any]:
        return {
            "provider_name": self.name,
            "provider_version": self.version,
            "provider_type": self.provider_type,
            "model_name": "noop",
            "model_version": self.version,
            "model_path": None,
            "model_checksums": {},
            "license": "Apache-2.0",
            "requires_network": False,
            "enabled_by_default": self.enabled_by_default,
            "safe_for_offline_use": True,
            "generative": False,
            "may_hallucinate": False,
            "provides_bboxes": False,
            "safe_for_image_redaction": False,
        }
