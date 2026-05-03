"""PII detection plugin interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..ocr.base import ProviderHealth
from .entities import PIIEntity


class PIIDetectionProvider(ABC):
    name: str = ""
    version: str = ""
    provider_type: str = "pii_detector"
    requires_network: bool = False
    enabled_by_default: bool = False

    supported_entities: list[str] = []
    supports_offsets: bool = False
    supports_bboxes: bool = False
    supports_confidence: bool = False

    @abstractmethod
    def load(self, config: dict[str, Any]) -> None: ...

    @abstractmethod
    def detect_text(self, text: str, context: dict[str, Any] | None = None) -> list[PIIEntity]:
        """Detect PII in a single text string. Must not log raw PII."""

    def detect_document_ir(self, document_ir, regions=None) -> list[PIIEntity]:
        """Default implementation: walk every word's text and run detect_text per page.

        Subclasses may override for more efficient batch processing.
        """
        results: list[PIIEntity] = []
        for page in document_ir.pages:
            page_text = " ".join(w.text for w in page.words)
            for entity in self.detect_text(page_text, context={"page_index": page.page_index}):
                entity.page_index = page.page_index
                results.append(entity)
        return results

    @abstractmethod
    def healthcheck(self) -> ProviderHealth: ...

    @abstractmethod
    def get_model_manifest(self) -> dict[str, Any]: ...

    def close(self) -> None:
        return None
