"""OCR plugin interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from .result import OCRResult


@dataclass
class ProviderHealth:
    healthy: bool
    detail: str = ""


class OCRProvider(ABC):
    name: str = ""
    version: str = ""
    provider_type: str = "traditional_ocr"
    requires_network: bool = False
    enabled_by_default: bool = False

    supports_pdf: bool = False
    supports_image: bool = True
    supports_word_bboxes: bool = False
    supports_line_bboxes: bool = False
    supports_confidence: bool = False

    @abstractmethod
    def load(self, config: dict[str, Any]) -> None:
        """Initialize the provider from local-only config. Must not download anything."""

    @abstractmethod
    def process_page_image(self, image: Any, page_context: dict[str, Any]) -> OCRResult:
        """Run OCR on a single rendered page image."""

    @abstractmethod
    def healthcheck(self) -> ProviderHealth:
        """Cheap probe used by the registry and CLI to confirm the provider is usable."""

    @abstractmethod
    def get_model_manifest(self) -> dict[str, Any]:
        """Return a manifest entry: name, version, model_path, checksums, license, network requirement, etc."""

    def close(self) -> None:
        return None
