"""Document-AI / VLM provider registry."""
from __future__ import annotations

from ..core.errors import PluginNotFoundError
from .base import DocumentAIProvider


class DocumentAIRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, type[DocumentAIProvider]] = {}

    def register(self, name: str, provider_cls: type[DocumentAIProvider]) -> None:
        if not isinstance(provider_cls, type) or not issubclass(provider_cls, DocumentAIProvider):
            raise TypeError(f"{provider_cls!r} is not a DocumentAIProvider subclass")
        self._providers[name] = provider_cls

    def get(self, name: str) -> type[DocumentAIProvider]:
        if name not in self._providers:
            raise PluginNotFoundError(
                f"Document-AI provider '{name}' is not registered. "
                f"Known providers: {sorted(self._providers)}"
            )
        return self._providers[name]

    def has(self, name: str) -> bool:
        return name in self._providers

    def names(self) -> list[str]:
        return sorted(self._providers)


_registry: DocumentAIRegistry | None = None


def get_registry() -> DocumentAIRegistry:
    global _registry
    if _registry is None:
        _registry = DocumentAIRegistry()
        from .providers.kosmos25_provider import Kosmos25Provider
        from .providers.layoutlm_provider import LayoutLMProvider
        from .providers.mock_vlm_provider import MockVLMProvider

        _registry.register("mock_vlm", MockVLMProvider)
        # Phase 5 skeleton — DISABLED BY DEFAULT in config.yaml. Loads
        # only from a local model directory with `local_files_only=True`
        # and the Hugging Face offline env vars set.
        _registry.register("kosmos25", Kosmos25Provider)
        # Phase 10 LayoutLM plugin — DISABLED BY DEFAULT, suggestion-
        # only, never drives export. Local-only; rejects allow_network
        # and local_files_only=False at load. See plugin docstring for
        # the full safety guarantees.
        _registry.register("layoutlm", LayoutLMProvider)
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None
