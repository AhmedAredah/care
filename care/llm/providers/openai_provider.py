"""OpenAI cloud provider (Phase 12).

DISABLED BY DEFAULT. Requires network. Sends data outside the local
environment. Refused in offline mode. The vendor SDK (``openai``) is
imported only inside ``load()`` so the plugin module remains importable
in environments without the package installed.

The provider talks to OpenAI's chat-completions API for both text and
vision tasks. Images are read locally and base64-encoded into a data
URL before send — never a URL the API would have to fetch — so the
egress posture is fully under operator control.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ...core.errors import ConfigError
from ...ocr.base import ProviderHealth
from ..base import LLMProvider, LLMResult
from ..image_encoding import image_to_data_url
from ..safety import redact_secrets, reject_in_offline_mode

_log = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 1024
_DEFAULT_TEMPERATURE = 0.0  # deterministic by default; overridable per call


class OpenAIProvider(LLMProvider):
    provider_name = "openai"
    provider_type = "cloud_llm_provider"
    vendor = "OpenAI"
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
        self._client: Any = None
        self._model: str = "gpt-4o-mini"

    # ---- lifecycle --------------------------------------------------

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
                f"{self.provider_name}: cloud LLMs send data outside the "
                "local environment. Set "
                "acknowledged_external_data_egress=true in this provider's "
                "config to confirm before enabling."
            )
        if not config.get("api_key"):
            raise ConfigError(f"{self.provider_name}: api_key is required")

        self._client = self._build_client(config)
        self._model = str(config.get("model") or self._model)
        # Persist a redacted copy so the manifest path can return it
        # without needing the raw config.
        self._config = dict(config)
        self._loaded = True

    @staticmethod
    def _build_client(config: dict[str, Any]) -> Any:
        """Construct an ``openai.OpenAI`` client.

        Factored out so tests can monkeypatch a fake client without
        installing the SDK and without having a real API key. The
        SDK is imported here, not at module top, so the file remains
        importable in environments without the dependency.
        """
        try:
            from openai import OpenAI  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ConfigError(
                "openai SDK is not installed. Install via offline "
                "wheelhouse before enabling the openai provider."
            ) from exc
        kwargs: dict[str, Any] = {"api_key": config["api_key"]}
        if config.get("base_url"):
            kwargs["base_url"] = config["base_url"]
        if config.get("organization"):
            kwargs["organization"] = config["organization"]
        if config.get("timeout") is not None:
            kwargs["timeout"] = config["timeout"]
        return OpenAI(**kwargs)

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=self._loaded,
            detail=f"model={self._model}" if self._loaded else "not loaded",
        )

    def get_model_manifest(self) -> dict[str, Any]:
        safe_config = redact_secrets(self._config)
        return {
            "provider_name": self.provider_name,
            "vendor": self.vendor,
            "model_name": self._model,
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

    # ---- inference --------------------------------------------------

    def generate_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> LLMResult:
        self._require_loaded()
        messages = self._build_messages(prompt=prompt, system=system)
        return self._chat_complete(messages=messages, json_schema=json_schema, **kwargs)

    def analyze_image(
        self,
        image_path: str,
        prompt: str,
        *,
        json_schema: dict[str, Any] | None = None,
        system: str | None = None,
        **kwargs: Any,
    ) -> LLMResult:
        self._require_loaded()
        if not Path(image_path).exists():
            raise FileNotFoundError(f"image not found: {image_path}")
        data_url = image_to_data_url(image_path)
        user_content: list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user_content})
        return self._chat_complete(messages=messages, json_schema=json_schema, **kwargs)

    # ---- internals --------------------------------------------------

    def _require_loaded(self) -> None:
        if not self._loaded or self._client is None:
            raise RuntimeError(f"{self.provider_name} provider is not loaded")

    @staticmethod
    def _build_messages(
        *, prompt: str, system: str | None
    ) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _chat_complete(
        self,
        *,
        messages: list[dict[str, Any]],
        json_schema: dict[str, Any] | None,
        **kwargs: Any,
    ) -> LLMResult:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": int(kwargs.get("max_tokens", _DEFAULT_MAX_TOKENS)),
            "temperature": float(kwargs.get("temperature", _DEFAULT_TEMPERATURE)),
        }
        if json_schema:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": str(kwargs.get("schema_name", "care")),
                    "schema": json_schema,
                    "strict": bool(kwargs.get("strict", True)),
                },
            }

        response = self._client.chat.completions.create(**request)
        return _response_to_llm_result(
            response,
            provider_name=self.provider_name,
            wants_structured=bool(json_schema),
        )


def _response_to_llm_result(
    response: Any, *, provider_name: str, wants_structured: bool
) -> LLMResult:
    """Convert an OpenAI ChatCompletion-shaped response into LLMResult.

    Works against both the real SDK return value and a duck-typed test
    double — we only touch the documented public surface
    (``choices[0].message.content``, ``finish_reason``, ``model``,
    ``usage``).
    """
    choices = getattr(response, "choices", None) or []
    if not choices:
        return LLMResult(
            text=None,
            provider=provider_name,
            model=str(getattr(response, "model", "")),
            finish_reason="empty",
            warnings=["LLM_OUTPUT_UNMAPPED"],
        )
    choice = choices[0]
    message = getattr(choice, "message", None)
    text = getattr(message, "content", None) if message is not None else None
    structured: dict[str, Any] | None = None
    warnings: list[str] = []
    if wants_structured and isinstance(text, str) and text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            warnings.append("LLM_OUTPUT_UNMAPPED")
        else:
            if isinstance(parsed, dict):
                structured = parsed
            else:
                warnings.append("LLM_OUTPUT_UNMAPPED")

    usage_obj = getattr(response, "usage", None)
    usage: dict[str, int] = {}
    if usage_obj is not None:
        # Real SDK exposes ``model_dump``; tests pass plain dicts.
        if hasattr(usage_obj, "model_dump"):
            try:
                dumped = usage_obj.model_dump()
            except Exception:  # noqa: BLE001
                dumped = {}
        elif isinstance(usage_obj, dict):
            dumped = usage_obj
        else:
            dumped = {}
        for key, value in dumped.items():
            if isinstance(value, int):
                usage[key] = value

    return LLMResult(
        text=text if isinstance(text, str) else None,
        structured=structured,
        provider=provider_name,
        model=str(getattr(response, "model", "")),
        finish_reason=str(getattr(choice, "finish_reason", "") or ""),
        usage=usage,
        warnings=warnings,
        requires_review=True,
    )
