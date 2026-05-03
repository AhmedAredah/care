"""Vendor-agnostic LLM/VLM plugin layer (Phase 12).

The package introduces a generic provider abstraction (``LLMProvider``)
and four categories — cloud LLM, local LLM, local VLM, and the
existing document-AI providers (which keep their separate base in
``care.document_ai``).

Every provider here is a plugin. The core pipeline never imports a
specific vendor; it depends on ``LLMProvider`` and the registry only.
LLM/VLM output is suggestion-only — it cannot drive public export, PII
detection, or image redaction.
"""
from .base import (
    LLMProvider,
    LLMResult,
    PROVIDER_TYPES,
)
from .registry import LLMRegistry, get_registry, reset_registry
from .safety import (
    is_loopback_url,
    redact_secrets,
)

__all__ = [
    "LLMProvider",
    "LLMRegistry",
    "LLMResult",
    "PROVIDER_TYPES",
    "get_registry",
    "is_loopback_url",
    "redact_secrets",
    "reset_registry",
]
