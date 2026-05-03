"""vLLM OpenAI-compatible local-server provider (Phase 12)."""
from __future__ import annotations

from ._local_server import LocalServerProviderBase


class VLLMProvider(LocalServerProviderBase):
    provider_name = "vllm"
    provider_type = "local_llm_provider"
    vendor = "vLLM (community)"
    supports_text = True
    supports_vision = True
    supports_pdf = False
    supports_json_schema_output = True
    default_endpoint = "http://127.0.0.1:8000"
