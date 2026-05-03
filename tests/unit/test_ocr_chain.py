"""OCR chain fallback tests (Phase 5 — provider chain in workers/pipeline)."""
from __future__ import annotations

from typing import Any

import pytest

from care.ocr.base import OCRProvider, ProviderHealth
from care.ocr.result import OCRResult, OCRWord
from care.workers.pipeline import _ocr_with_chain


class _AlwaysFails(OCRProvider):
    name = "always_fails"
    version = "0.0.0"
    provider_type = "traditional_ocr"

    def load(self, config: dict[str, Any]) -> None:
        return None

    def process_page_image(self, image: Any, page_context: dict[str, Any]) -> OCRResult:
        raise RuntimeError("simulated provider failure")

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=False, detail="always fails")

    def get_model_manifest(self) -> dict[str, Any]:
        return {"provider_name": self.name, "provider_version": self.version}


class _AlwaysSucceeds(OCRProvider):
    name = "always_ok"
    version = "0.0.0"
    provider_type = "traditional_ocr"

    def load(self, config: dict[str, Any]) -> None:
        return None

    def process_page_image(self, image: Any, page_context: dict[str, Any]) -> OCRResult:
        return OCRResult(
            words=[OCRWord(text="OK", bbox=[0, 0, 10, 10], confidence=0.9)],
            lines=[],
            blocks=[],
            confidence=0.9,
            provider_name=self.name,
            provider_version=self.version,
            can_map_to_image_coordinates=True,
        )

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(healthy=True)

    def get_model_manifest(self) -> dict[str, Any]:
        return {"provider_name": self.name, "provider_version": self.version}


def test_ocr_chain_falls_back_when_first_provider_raises() -> None:
    chain = [_AlwaysFails(), _AlwaysSucceeds()]
    result, used = _ocr_with_chain("dummy.png", {"page_index": 0, "dpi": 200}, chain)
    assert used == "always_ok"
    assert result.words[0].text == "OK"


def test_ocr_chain_returns_first_success_without_calling_later() -> None:
    """Ensure providers AFTER the first success are never invoked."""
    calls: list[str] = []

    class _Counting(_AlwaysSucceeds):
        name = "counting"

        def process_page_image(self, image, page_context):
            calls.append(self.name)
            return super().process_page_image(image, page_context)

    p1 = _Counting()
    p2 = _Counting()
    chain = [p1, p2]
    _, used = _ocr_with_chain("dummy.png", {"page_index": 0, "dpi": 200}, chain)
    assert used == "counting"
    assert len(calls) == 1


def test_ocr_chain_raises_when_every_provider_fails() -> None:
    chain = [_AlwaysFails(), _AlwaysFails()]
    with pytest.raises(RuntimeError, match="All OCR providers in chain failed"):
        _ocr_with_chain("dummy.png", {"page_index": 0, "dpi": 200}, chain)
