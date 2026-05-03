"""Google Gemini cloud provider (Phase 12).

DISABLED BY DEFAULT. Network required. Sends data to Google. Refused
in offline mode. SDK (``google.generativeai`` or ``google.genai``)
imported inside ``load()``.
"""
from __future__ import annotations

from typing import Any

from ...core.errors import ConfigError
from ...ocr.base import ProviderHealth
from ..base import LLMProvider
from ..safety import redact_secrets, reject_in_offline_mode


class GeminiProvider(LLMProvider):
    provider_name = "gemini"
    provider_type = "cloud_llm_provider"
    vendor = "Google"
    supports_text = True
    supports_vision = True
    supports_pdf = True
    supports_json_schema_output = True
    supports_local_offline = False
    requires_network = True
    enabled_by_default = False

    def __init__(self) -> None:
        self._loaded = False
        self._config: dict[str, Any] = {}

    def load(self, config: dict[str, Any]) -> None:
        offline_enabled = bool(
            (config.get("_app_config") or {}).get("offline_enabled", False)
        )
        reject_in_offline_mode(
            self.provider_name,
            requires_network=self.requires_network,
            offline_enabled=offline_enabled,
        )
        if not config.get("acknowledged_external_data_egress"):
            raise ConfigError(
                f"{self.provider_name}: set "
                "acknowledged_external_data_egress=true to confirm before "
                "enabling a cloud provider."
            )
        if not config.get("api_key"):
            raise ConfigError(f"{self.provider_name}: api_key is required")
        try:
            import google.generativeai  # type: ignore[import-not-found]  # noqa: F401
        except ImportError:
            try:
                import google.genai  # type: ignore[import-not-found]  # noqa: F401
            except ImportError as exc:
                raise ConfigError(
                    f"{self.provider_name}: google.generativeai / google.genai "
                    "SDK is not installed."
                ) from exc
        self._config = dict(config)
        self._loaded = True

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=self._loaded,
            detail="gemini" if self._loaded else "not loaded",
        )

    def get_model_manifest(self) -> dict[str, Any]:
        safe_config = redact_secrets(self._config)
        return {
            "provider_name": self.provider_name,
            "vendor": self.vendor,
            "model_name": safe_config.get("model", "gemini-1.5-flash"),
            "model_version": safe_config.get("model_version", "live"),
            "endpoint_type": "cloud",
            "requires_network": True,
            "sends_data_external": True,
            "local_files_only": False,
            "supports_vision": self.supports_vision,
            "supports_pdf": self.supports_pdf,
            "supports_structured_output": self.supports_json_schema_output,
            "license": "vendor TOS — review with legal",
            "enabled_by_default": False,
            "safe_for_export_decision": False,
            "safe_for_image_redaction": False,
            "config": safe_config,
        }
