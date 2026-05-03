"""Deterministic mock LLM provider for tests."""
from __future__ import annotations

from typing import Any, Optional

from ...ocr.base import ProviderHealth
from ..base import LLMProvider, LLMResult


class MockLLMProvider(LLMProvider):
    provider_name = "mock_llm"
    provider_type = "local_llm_provider"
    vendor = "care"
    supports_text = True
    supports_vision = True
    supports_pdf = False
    supports_json_schema_output = True
    supports_local_offline = True
    requires_network = False
    enabled_by_default = False

    def __init__(self) -> None:
        self._loaded = False
        self._fixture: dict[str, Any] = {}

    def load(self, config: dict[str, Any]) -> None:
        self._fixture = dict(config.get("fixture") or {})
        self._loaded = True

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=self._loaded, detail="mock_llm" if self._loaded else "not loaded"
        )

    def get_model_manifest(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "vendor": self.vendor,
            "model_name": "mock",
            "model_version": "0",
            "endpoint_type": "local",
            "requires_network": False,
            "sends_data_external": False,
            "local_files_only": True,
            "supports_vision": self.supports_vision,
            "supports_pdf": self.supports_pdf,
            "supports_structured_output": self.supports_json_schema_output,
            "license": "MIT (in-repo)",
            "enabled_by_default": False,
            "safe_for_export_decision": False,
            "safe_for_image_redaction": False,
        }

    def generate_text(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        json_schema: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> LLMResult:
        text = str(self._fixture.get("text", f"mock response: {prompt[:48]}"))
        return LLMResult(
            text=text,
            structured=self._fixture.get("structured"),
            provider=self.provider_name,
            model="mock",
            warnings=list(self._fixture.get("warnings") or []),
        )

    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        *,
        json_schema: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> LLMResult:
        return LLMResult(
            text=f"mock vision: {prompt[:48]} on {image_path}",
            provider=self.provider_name,
            model="mock-vision",
        )
