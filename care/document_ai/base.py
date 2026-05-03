"""Document-AI / VLM plugin interface.

VLM plugins are *generative* by default. The reconciliation stage and
QA gate (Phase 3+) are responsible for ensuring VLM output never
silently drives image redaction or final narrative export.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from ..ocr.base import ProviderHealth
from .result import (
    DocumentAIResult,
    DocumentQAResult,
    MarkdownResult,
    RegionDetectionResult,
    SpatialTextResult,
)


class DocumentAIProvider(ABC):
    name: str = ""
    version: str = ""
    provider_type: str = "vlm_document_parser"
    requires_network: bool = False
    enabled_by_default: bool = False

    supports_image_to_text: bool = False
    supports_image_to_markdown: bool = False
    supports_spatial_text: bool = False
    supports_region_detection: bool = False
    supports_question_answering: bool = False
    supports_confidence: bool = False

    generative_model: bool = True
    hallucination_risk: bool = True

    # See OCRProvider.accuracy_metrics for the schema. VLM benchmarks
    # are typically Tier C (vendor / unverified) until a fair in-domain
    # eval set exists; the UI must show the tier badge.
    accuracy_metrics: Optional[dict[str, Any]] = None

    @abstractmethod
    def load(self, config: dict[str, Any]) -> None: ...

    @abstractmethod
    def process_page_image(
        self, image: Any, page_context: dict[str, Any], task: str
    ) -> DocumentAIResult: ...

    def image_to_spatial_text(
        self, image: Any, page_context: dict[str, Any]
    ) -> SpatialTextResult:
        raise NotImplementedError(f"{self.name} does not support spatial text")

    def image_to_markdown(
        self, image: Any, page_context: dict[str, Any]
    ) -> MarkdownResult:
        raise NotImplementedError(f"{self.name} does not support markdown")

    def detect_regions(
        self, image: Any, page_context: dict[str, Any]
    ) -> RegionDetectionResult:
        raise NotImplementedError(f"{self.name} does not support region detection")

    def ask_document_question(
        self, image: Any, question: str, page_context: dict[str, Any]
    ) -> DocumentQAResult:
        raise NotImplementedError(f"{self.name} does not support document QA")

    @abstractmethod
    def healthcheck(self) -> ProviderHealth: ...

    @abstractmethod
    def get_model_manifest(self) -> dict[str, Any]: ...

    def close(self) -> None:
        return None
