"""PII provider registry."""
from __future__ import annotations

from ..core.errors import PluginNotFoundError
from .base import PIIDetectionProvider


class PIIRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, type[PIIDetectionProvider]] = {}

    def register(self, name: str, provider_cls: type[PIIDetectionProvider]) -> None:
        if not isinstance(provider_cls, type) or not issubclass(provider_cls, PIIDetectionProvider):
            raise TypeError(f"{provider_cls!r} is not a PIIDetectionProvider subclass")
        self._providers[name] = provider_cls

    def get(self, name: str) -> type[PIIDetectionProvider]:
        if name not in self._providers:
            raise PluginNotFoundError(
                f"PII provider '{name}' is not registered. "
                f"Known providers: {sorted(self._providers)}"
            )
        return self._providers[name]

    def has(self, name: str) -> bool:
        return name in self._providers

    def names(self) -> list[str]:
        return sorted(self._providers)


_registry: PIIRegistry | None = None


def get_registry() -> PIIRegistry:
    global _registry
    if _registry is None:
        _registry = PIIRegistry()
        from .providers.mock_pii_provider import MockPIIProvider
        from .providers.openai_privacy_filter_provider import (
            OpenAIPrivacyFilterProvider,
        )
        from .providers.optional_piiranha_provider import PiiranhaPIIProvider
        from .providers.presidio_provider import PresidioPIIProvider
        from .providers.regex_provider import RegexPIIProvider
        from .providers.roberta_ner_provider import RobertaNERProvider

        _registry.register("mock_pii", MockPIIProvider)
        _registry.register("regex", RegexPIIProvider)
        # Optional skeletons — disabled by default. They only load
        # when local model files are present (Presidio) or when the
        # operator has accepted the license warning (Piiranha).
        _registry.register("presidio", PresidioPIIProvider)
        _registry.register("piiranha", PiiranhaPIIProvider)
        # General English NER (Jean-Baptiste/roberta-large-ner-english).
        # MIT-licensed, disabled by default. Supplements regex
        # recognizers for free-text names and locations.
        _registry.register("roberta_ner", RobertaNERProvider)
        # OpenAI Privacy Filter (openai/privacy-filter). Apache-2.0,
        # disabled by default. Bidirectional token-classification
        # model trained for high-throughput PII detection.
        _registry.register(
            "openai_privacy_filter", OpenAIPrivacyFilterProvider
        )
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None
