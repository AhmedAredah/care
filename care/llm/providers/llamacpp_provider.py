"""llama.cpp / LM Studio OpenAI-compatible local-server provider
(Phase 12).

LM Studio's "Local Server" mode and the llama.cpp ``llama-server``
both expose an OpenAI-compatible HTTP endpoint. They share this
provider class — operators distinguish them via the configured
endpoint URL.
"""
from __future__ import annotations

from ._local_server import LocalServerProviderBase


class LlamaCppProvider(LocalServerProviderBase):
    provider_name = "llamacpp"
    provider_type = "local_llm_provider"
    vendor = "llama.cpp / LM Studio"
    supports_text = True
    supports_vision = True
    supports_pdf = False
    supports_json_schema_output = True
    default_endpoint = "http://127.0.0.1:8080"
