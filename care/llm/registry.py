"""LLM provider registry."""
from __future__ import annotations

from typing import Type

from ..core.errors import PluginNotFoundError
from .base import LLMProvider


class LLMRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Type[LLMProvider]] = {}

    def register(self, name: str, provider_cls: Type[LLMProvider]) -> None:
        if not isinstance(provider_cls, type) or not issubclass(provider_cls, LLMProvider):
            raise TypeError(f"{provider_cls!r} is not an LLMProvider subclass")
        self._providers[name] = provider_cls

    def get(self, name: str) -> Type[LLMProvider]:
        if name not in self._providers:
            raise PluginNotFoundError(
                f"LLM provider '{name}' is not registered. "
                f"Known providers: {sorted(self._providers)}"
            )
        return self._providers[name]

    def has(self, name: str) -> bool:
        return name in self._providers

    def names(self) -> list[str]:
        return sorted(self._providers)


_registry: LLMRegistry | None = None


def get_registry() -> LLMRegistry:
    """Lazy-initialize the registry. Concrete providers are imported
    here so the registry module itself stays importable without any
    vendor SDK installed."""
    global _registry
    if _registry is None:
        _registry = LLMRegistry()
        # Cloud providers (DISABLED BY DEFAULT in config.yaml).
        from .providers.anthropic_provider import AnthropicProvider
        from .providers.gemini_provider import GeminiProvider
        from .providers.openai_provider import OpenAIProvider
        # Local-server providers (loopback enforced).
        from .providers.llamacpp_provider import LlamaCppProvider
        from .providers.ollama_provider import OllamaProvider
        from .providers.vllm_provider import VLLMProvider
        # Local-files provider (Hugging Face transformers).
        from .providers.hf_local_provider import HFLocalProvider
        # Mock — for tests only.
        from .providers.mock_llm_provider import MockLLMProvider

        _registry.register("openai", OpenAIProvider)
        _registry.register("gemini", GeminiProvider)
        _registry.register("anthropic", AnthropicProvider)
        _registry.register("ollama", OllamaProvider)
        _registry.register("vllm", VLLMProvider)
        _registry.register("llamacpp", LlamaCppProvider)
        _registry.register("hf_local", HFLocalProvider)
        _registry.register("mock_llm", MockLLMProvider)
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = None
