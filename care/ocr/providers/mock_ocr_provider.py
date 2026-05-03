"""Deterministic mock OCR provider used by tests and the offline demo."""
from __future__ import annotations

from typing import Any

from ..base import OCRProvider, ProviderHealth
from ..result import OCRBlock, OCRLine, OCRResult, OCRWord


class MockOCRProvider(OCRProvider):
    name = "mock_ocr"
    version = "0.1.0"
    provider_type = "traditional_ocr"
    requires_network = False
    enabled_by_default = False

    supports_pdf = False
    supports_image = True
    supports_word_bboxes = True
    supports_line_bboxes = True
    supports_confidence = True

    def __init__(self) -> None:
        self._loaded = False
        self._mock_tokens: list[str] | None = None

    def load(self, config: dict[str, Any]) -> None:
        self._loaded = True
        tokens = config.get("mock_tokens")
        if tokens is not None:
            if not isinstance(tokens, list) or not all(isinstance(t, str) for t in tokens):
                raise ValueError("mock_tokens must be a list[str]")
            self._mock_tokens = tokens

    def process_page_image(self, image: Any, page_context: dict[str, Any]) -> OCRResult:
        tokens = self._mock_tokens or ["MOCK", "REPORT"]
        words = [
            OCRWord(
                text=token,
                bbox=[i * 60, 0, i * 60 + 50, 20],
                confidence=0.97,
            )
            for i, token in enumerate(tokens)
        ]
        line_text = " ".join(tokens)
        line = OCRLine(
            text=line_text,
            bbox=[0, 0, max(len(tokens) * 60, 1), 20],
            confidence=0.97,
            word_indices=list(range(len(tokens))),
        )
        block = OCRBlock(text=line_text, bbox=line.bbox, line_indices=[0])
        return OCRResult(
            words=words,
            lines=[line],
            blocks=[block],
            confidence=0.97,
            provider_name=self.name,
            provider_version=self.version,
            can_map_to_image_coordinates=True,
        )

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
            "generative": False,
            "may_hallucinate": False,
            "provides_bboxes": True,
            "safe_for_image_redaction": True,
        }
