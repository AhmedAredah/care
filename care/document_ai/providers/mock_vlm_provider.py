"""Deterministic mock VLM provider used by tests.

Supports a `mock_mode` config key so tests can simulate:

- "default"           — well-formed spatial OCR + markdown output
- "no_bboxes"         — markdown only, no bounding boxes
- "conflict_with_ocr" — text that disagrees with the matching OCR result
- "hallucinated"      — extra invented text the OCR layer never saw
- "unmapped_pii"      — PII-shaped text without bounding boxes
"""
from __future__ import annotations

from typing import Any

from ...ocr.base import ProviderHealth
from ..base import DocumentAIProvider
from ..result import (
    CandidateRegion,
    DocumentAIResult,
    MarkdownResult,
    MarkdownSection,
    RegionDetectionResult,
    SpatialTextResult,
    SpatialWord,
)

VALID_MODES = {"default", "no_bboxes", "conflict_with_ocr", "hallucinated", "unmapped_pii"}


class MockVLMProvider(DocumentAIProvider):
    name = "mock_vlm"
    version = "0.1.0"
    provider_type = "vlm_document_parser"
    requires_network = False
    enabled_by_default = False

    supports_image_to_text = True
    supports_image_to_markdown = True
    supports_spatial_text = True
    supports_region_detection = True
    supports_question_answering = False
    supports_confidence = False

    generative_model = True
    hallucination_risk = True

    def __init__(self) -> None:
        self._loaded = False
        self._mode = "default"

    def load(self, config: dict[str, Any]) -> None:
        mode = config.get("mock_mode", "default")
        if mode not in VALID_MODES:
            raise ValueError(f"Unknown mock_mode {mode!r}; valid: {sorted(VALID_MODES)}")
        self._mode = mode
        self._loaded = True

    def process_page_image(
        self, image: Any, page_context: dict[str, Any], task: str
    ) -> DocumentAIResult:
        if task == "spatial_ocr":
            spatial = self.image_to_spatial_text(image, page_context)
            return DocumentAIResult(
                spatial_text=spatial,
                provider_name=self.name,
                provider_version=self.version,
                generative=self.generative_model,
                hallucination_risk=self.hallucination_risk,
                can_map_to_image_coordinates=spatial.can_map_to_image_coordinates,
            )
        if task == "markdown":
            md = self.image_to_markdown(image, page_context)
            return DocumentAIResult(
                markdown=md,
                provider_name=self.name,
                provider_version=self.version,
                generative=True,
                hallucination_risk=True,
                can_map_to_image_coordinates=False,
                warnings=["VLM_OUTPUT_HAS_NO_BBOXES"] if self._mode == "no_bboxes" else [],
            )
        raise ValueError(f"Unsupported task {task!r}")

    def image_to_spatial_text(self, image: Any, page_context: dict[str, Any]) -> SpatialTextResult:
        if self._mode == "no_bboxes":
            return SpatialTextResult(
                words=[SpatialWord(text="MOCK"), SpatialWord(text="REPORT")],
                can_map_to_image_coordinates=False,
                provider=self.name,
            )
        if self._mode == "hallucinated":
            return SpatialTextResult(
                words=[
                    SpatialWord(text="MOCK", bbox=[0, 0, 60, 20]),
                    SpatialWord(text="REPORT", bbox=[65, 0, 150, 20]),
                    SpatialWord(text="GHOST", bbox=[160, 0, 220, 20]),
                ],
                can_map_to_image_coordinates=True,
                provider=self.name,
            )
        if self._mode == "conflict_with_ocr":
            return SpatialTextResult(
                words=[
                    SpatialWord(text="M0CK", bbox=[0, 0, 60, 20]),
                    SpatialWord(text="REPORT", bbox=[65, 0, 150, 20]),
                ],
                can_map_to_image_coordinates=True,
                provider=self.name,
            )
        if self._mode == "unmapped_pii":
            return SpatialTextResult(
                words=[SpatialWord(text="JOHN DOE 555-123-4567")],
                can_map_to_image_coordinates=False,
                provider=self.name,
            )
        return SpatialTextResult(
            words=[
                SpatialWord(text="MOCK", bbox=[0, 0, 60, 20]),
                SpatialWord(text="REPORT", bbox=[65, 0, 150, 20]),
            ],
            can_map_to_image_coordinates=True,
            provider=self.name,
        )

    def image_to_markdown(self, image: Any, page_context: dict[str, Any]) -> MarkdownResult:
        body = "Synthetic narrative text for testing only."
        sections = [
            MarkdownSection(heading="Narrative", body=body),
        ]
        return MarkdownResult(
            markdown=f"# Narrative\n\n{body}\n",
            sections=sections,
            provider=self.name,
        )

    def detect_regions(self, image: Any, page_context: dict[str, Any]) -> RegionDetectionResult:
        return RegionDetectionResult(
            regions=[
                CandidateRegion(label="diagram", bbox=[100, 200, 800, 600], confidence=0.6),
                CandidateRegion(label="narrative", bbox=[100, 700, 800, 1000], confidence=0.65),
            ],
            provider=self.name,
        )

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=self._loaded, detail=f"mock mode={self._mode}")

    def get_model_manifest(self) -> dict[str, Any]:
        return {
            "provider_name": self.name,
            "provider_version": self.version,
            "provider_type": self.provider_type,
            "model_name": "mock-vlm",
            "model_version": self.version,
            "model_path": None,
            "model_checksums": {},
            "license": "Apache-2.0",
            "requires_network": self.requires_network,
            "enabled_by_default": self.enabled_by_default,
            "safe_for_offline_use": True,
            "generative": True,
            "may_hallucinate": True,
            "provides_bboxes": self._mode != "no_bboxes",
            "safe_for_image_redaction": False,
        }
