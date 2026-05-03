"""Generic LLM/VLM provider interface (Phase 12).

This abstraction is **vendor-agnostic by construction**: the core
pipeline imports ``LLMProvider`` and the registry only — never a
specific vendor SDK or class. Every concrete provider is a plugin
that lives under :mod:`care.llm.providers`.

Provider categories (declared by the concrete class via
``provider_type``):

- ``cloud_llm_provider`` — OpenAI, Gemini, Anthropic, etc. Network
  required. Sends data outside the local environment. Disabled by
  default. Refused in offline mode.
- ``local_llm_provider`` — Ollama, vLLM, llama.cpp, LM Studio. Talks
  to a server on the local host. Loopback URL required unless the
  operator explicitly opts in to a remote endpoint.
- ``local_vlm_provider`` — local vision-capable models that produce
  text (e.g., a multimodal Ollama model). Same loopback rules as
  ``local_llm_provider``.
- ``document_ai_provider`` — bbox-aware document parsers (Kosmos-2.5,
  LayoutLM). These keep their own Phase 1 base in
  :mod:`care.document_ai`; they are *also* exposed here for
  registry parity.

Output safety guarantees — every provider:

- ``get_model_manifest()`` MUST redact API keys via
  :func:`care.llm.safety.redact_secrets`.
- LLM/VLM output is **suggestion-only**. It can produce regions,
  anchors, labels, or QA second-opinions, and nothing else. It can
  NOT drive public export, override template extraction, override
  PII detection, or drive image redaction without a downstream
  human-review step.
- Any pipeline run that consumes LLM/VLM output must surface
  ``LLM_REQUIRES_REVIEW`` (Phase 12 QA flag) so the QA gate forces
  ``requires_human_review = True``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ..ocr.base import ProviderHealth

PROVIDER_TYPES: frozenset[str] = frozenset({
    "cloud_llm_provider",
    "local_llm_provider",
    "local_vlm_provider",
    "document_ai_provider",
})


@dataclass
class LLMResult:
    """Uniform result envelope for every provider call.

    Either ``text`` is set (chat/completion output) OR ``structured``
    is set (a JSON-schema-conformant dict), or both. ``provider`` and
    ``model`` populate the audit trail. ``warnings`` accumulates any
    non-fatal signals the provider wants to surface — the QA gate
    converts them to flags downstream.
    """

    text: Optional[str] = None
    structured: Optional[dict[str, Any]] = None
    provider: str = ""
    model: str = ""
    finish_reason: Optional[str] = None
    usage: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    requires_review: bool = True


class LLMProvider(ABC):
    """Vendor-agnostic LLM/VLM plugin interface.

    Concrete subclasses populate the class-level capability flags
    (``supports_*``) and the ``provider_type`` discriminator, then
    implement ``load()``, ``healthcheck()``, ``get_model_manifest()``,
    and one or more of ``generate_text()`` / ``analyze_image()`` /
    ``analyze_document()`` depending on what the underlying model
    supports.

    Class-level fields (override on the concrete class):

    - ``provider_name`` — human-readable id, e.g. ``"openai"``.
    - ``provider_type`` — one of :data:`PROVIDER_TYPES`.
    - ``vendor`` — vendor name for audit, e.g. ``"OpenAI"``.
    - ``supports_text`` / ``supports_vision`` / ``supports_pdf`` —
      capability flags. Default to ``False``; concrete classes flip
      what's true.
    - ``supports_json_schema_output`` — provider can emit structured
      output that conforms to a caller-supplied JSON schema.
    - ``supports_local_offline`` — provider works without network.
    - ``requires_network`` — provider MUST have network. Mutually
      exclusive with offline mode.
    - ``enabled_by_default`` — default ``False`` for every concrete
      provider, even mocks. The policy checker enforces this.
    """

    # Discriminators / flags — concrete classes override.
    provider_name: str = ""
    provider_type: str = ""
    vendor: str = ""
    supports_text: bool = False
    supports_vision: bool = False
    supports_pdf: bool = False
    supports_json_schema_output: bool = False
    supports_local_offline: bool = False
    requires_network: bool = False
    enabled_by_default: bool = False

    # Default safety posture for every provider in this layer. The
    # only way these flip True is at the per-record level after a
    # human review accepts the output into a template.
    safe_for_export_decision: bool = False
    safe_for_image_redaction: bool = False

    @abstractmethod
    def load(self, config: dict[str, Any]) -> None:
        """Validate config + prepare the provider for inference.

        Concrete implementations must:

        1. Reject any config flag that would weaken safety (e.g.,
           ``allow_network=true`` in offline mode for cloud
           providers, non-loopback URL without
           ``allow_non_loopback=true`` for local-server providers).
        2. Defer vendor SDK imports to inside ``load()`` so the
           plugin module remains importable without the SDK
           installed.
        3. Redact API keys from internal state used by
           :py:meth:`get_model_manifest`.
        """

    @abstractmethod
    def healthcheck(self) -> ProviderHealth: ...

    @abstractmethod
    def get_model_manifest(self) -> dict[str, Any]:
        """Return the audit manifest entry. Must be safe to log.

        Required keys (per Phase 12 spec):

        - ``provider_name`` / ``vendor`` / ``model_name`` /
          ``model_version`` / ``endpoint_type`` / ``requires_network``
          / ``sends_data_external`` / ``local_files_only`` /
          ``supports_vision`` / ``supports_pdf`` /
          ``supports_structured_output`` / ``license`` /
          ``enabled_by_default`` / ``safe_for_export_decision`` /
          ``safe_for_image_redaction``.

        API-key-shaped fields MUST be redacted via
        :func:`care.llm.safety.redact_secrets`.
        """

    # Optional capabilities — concrete classes override what they
    # actually implement. Default raises NotImplementedError so a
    # caller that asks for an unsupported task fails loudly.

    def generate_text(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        json_schema: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> LLMResult:
        raise NotImplementedError(
            f"{self.provider_name} does not support text generation"
        )

    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        *,
        json_schema: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> LLMResult:
        raise NotImplementedError(
            f"{self.provider_name} does not support image analysis"
        )

    def analyze_document(
        self,
        document_path: str,
        prompt: str,
        *,
        json_schema: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> LLMResult:
        raise NotImplementedError(
            f"{self.provider_name} does not support document analysis"
        )

    def close(self) -> None:
        return None
