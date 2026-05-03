"""Shared scaffolding for local-server LLM providers (Ollama, vLLM,
llama.cpp, LM Studio).

Each of these vendors exposes an HTTP endpoint, typically on
loopback. The common code:

- Validates ``endpoint_url`` (loopback by default; non-loopback only
  with explicit operator opt-in).
- Forbids non-loopback endpoints in offline mode.
- Persists a redacted config copy for the manifest.

Concrete subclasses populate ``provider_name``, ``vendor``, the
capability flags, and a default endpoint URL.
"""
from __future__ import annotations

from typing import Any

from ...ocr.base import ProviderHealth
from ..base import LLMProvider
from ..safety import assert_loopback_or_explicit, is_loopback_url, redact_secrets


class LocalServerProviderBase(LLMProvider):
    """Base class for any provider that talks to a local HTTP server.

    Subclasses must override the class-level identifiers and
    ``default_endpoint``. They typically don't need to override
    ``load()`` — the base implementation handles the safety checks.
    """

    provider_type = "local_llm_provider"
    supports_text = True
    supports_local_offline = True
    requires_network = False
    enabled_by_default = False
    default_endpoint = "http://127.0.0.1:11434"
    license = "varies — see model card"

    def __init__(self) -> None:
        self._loaded = False
        self._endpoint: str = ""
        self._allow_non_loopback: bool = False
        self._config: dict[str, Any] = {}

    def load(self, config: dict[str, Any]) -> None:
        endpoint = str(config.get("endpoint_url") or self.default_endpoint)
        allow_non_loopback = bool(config.get("allow_non_loopback", False))
        offline_enabled = bool(
            (config.get("_app_config") or {}).get("offline_enabled", False)
        )
        assert_loopback_or_explicit(
            self.provider_name,
            endpoint_url=endpoint,
            allow_non_loopback=allow_non_loopback,
            offline_enabled=offline_enabled,
        )
        self._endpoint = endpoint
        self._allow_non_loopback = allow_non_loopback
        self._config = dict(config)
        self._loaded = True

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=self._loaded,
            detail=f"endpoint={self._endpoint}" if self._loaded else "not loaded",
        )

    def get_model_manifest(self) -> dict[str, Any]:
        endpoint_type = "loopback" if is_loopback_url(self._endpoint) else "local"
        safe_config = redact_secrets(self._config)
        sends_external = (
            (not is_loopback_url(self._endpoint)) and self._allow_non_loopback
        )
        return {
            "provider_name": self.provider_name,
            "vendor": self.vendor,
            "model_name": safe_config.get("model", "unknown"),
            "model_version": safe_config.get("model_version", "local"),
            "endpoint_type": endpoint_type,
            "endpoint_url": self._endpoint,
            "requires_network": False,
            "sends_data_external": sends_external,
            "local_files_only": False,
            "supports_vision": self.supports_vision,
            "supports_pdf": self.supports_pdf,
            "supports_structured_output": self.supports_json_schema_output,
            "license": getattr(self, "license", "varies"),
            "enabled_by_default": False,
            "safe_for_export_decision": False,
            "safe_for_image_redaction": False,
            "config": safe_config,
        }
