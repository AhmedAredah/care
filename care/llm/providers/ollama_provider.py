"""Ollama local-server LLM/VLM provider (Phase 12).

Disabled by default. Talks to ``http://127.0.0.1:11434`` by default.
Non-loopback endpoints require ``allow_non_loopback=true`` and are
forbidden in offline mode.
"""
from __future__ import annotations

from ._local_server import LocalServerProviderBase


class OllamaProvider(LocalServerProviderBase):
    provider_name = "ollama"
    provider_type = "local_llm_provider"
    vendor = "Ollama"
    supports_text = True
    supports_vision = True  # multimodal models (e.g., llava) supported
    supports_pdf = False
    supports_json_schema_output = True
    default_endpoint = "http://127.0.0.1:11434"
