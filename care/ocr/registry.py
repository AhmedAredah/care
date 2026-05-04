"""OCR provider registry.

Only locally declared plugins are accepted. Unknown names are rejected
unless explicitly registered.
"""
from __future__ import annotations

from ..core.errors import PluginNotFoundError
from .base import OCRProvider


class OCRRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, type[OCRProvider]] = {}

    def register(self, name: str, provider_cls: type[OCRProvider]) -> None:
        if not isinstance(provider_cls, type) or not issubclass(provider_cls, OCRProvider):
            raise TypeError(f"{provider_cls!r} is not an OCRProvider subclass")
        self._providers[name] = provider_cls

    def get(self, name: str) -> type[OCRProvider]:
        if name not in self._providers:
            raise PluginNotFoundError(
                f"OCR provider '{name}' is not registered. "
                f"Known providers: {sorted(self._providers)}"
            )
        return self._providers[name]

    def has(self, name: str) -> bool:
        return name in self._providers

    def names(self) -> list[str]:
        return sorted(self._providers)


_registry: OCRRegistry | None = None


def get_registry() -> OCRRegistry:
    global _registry
    if _registry is None:
        _registry = OCRRegistry()
        from .providers.mock_ocr_provider import MockOCRProvider
        from .providers.noop_provider import NoopOCRProvider
        from .providers.onnxtr_provider import OnnxTROCRProvider
        from .providers.paddleocr_provider import PaddleOCRProvider
        from .providers.tesseract_provider import TesseractProvider

        _registry.register("mock_ocr", MockOCRProvider)
        _registry.register("noop", NoopOCRProvider)
        # Real OCR providers are registered but disabled-by-default; they
        # only load when local model files are present (GOVERNANCE.md
        # §License and Model Governance).
        _registry.register("paddleocr", PaddleOCRProvider)
        _registry.register("tesseract", TesseractProvider)
        _registry.register("onnxtr", OnnxTROCRProvider)
    return _registry


def reset_registry() -> None:
    """Test helper. Resets the module-level singleton."""
    global _registry
    _registry = None
