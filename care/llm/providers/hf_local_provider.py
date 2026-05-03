"""Hugging Face local-files LLM provider (Phase 12).

Loads a Transformers model from a local directory only —
``local_files_only=True`` is enforced and the HF offline env vars are
re-applied on every load. No HTTP endpoint, no network.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Optional

from ...core.constants import HF_OFFLINE_ENV
from ...core.errors import ConfigError, OfflineGuardError
from ...ocr.base import ProviderHealth
from ..base import LLMProvider
from ..safety import redact_secrets


class HFLocalProvider(LLMProvider):
    provider_name = "hf_local"
    provider_type = "local_llm_provider"
    vendor = "Hugging Face (local)"
    supports_text = True
    supports_vision = False  # opt in by subclassing for VLM checkpoints
    supports_pdf = False
    supports_json_schema_output = False
    supports_local_offline = True
    requires_network = False
    enabled_by_default = False

    def __init__(self) -> None:
        self._loaded = False
        self._model_dir: Optional[Path] = None
        self._config: dict[str, Any] = {}
        self._checksums: dict[str, str] = {}

    def load(self, config: dict[str, Any]) -> None:
        if config.get("allow_network", False):
            raise ConfigError(f"{self.provider_name}: allow_network must be false")
        if not config.get("local_files_only", True):
            raise ConfigError(
                f"{self.provider_name}: local_files_only must be true"
            )
        for key, value in HF_OFFLINE_ENV.items():
            os.environ[key] = value
        model_dir = Path(config.get("model_dir") or "")
        if not str(model_dir) or not model_dir.exists():
            raise OfflineGuardError(
                f"{self.provider_name}: model_dir not found at {model_dir!s}"
            )
        try:
            import transformers  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:
            raise ConfigError(
                f"{self.provider_name}: transformers is not installed"
            ) from exc
        self._model_dir = model_dir
        self._config = dict(config)
        self._checksums = self._compute_checksums(model_dir)
        self._loaded = True

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=self._loaded,
            detail=f"model_dir={self._model_dir}" if self._loaded else "not loaded",
        )

    def get_model_manifest(self) -> dict[str, Any]:
        safe_config = redact_secrets(self._config)
        return {
            "provider_name": self.provider_name,
            "vendor": self.vendor,
            "model_name": safe_config.get("model", "local-checkpoint"),
            "model_version": safe_config.get("model_version", "local"),
            "endpoint_type": "local",
            "model_path": str(self._model_dir) if self._model_dir else None,
            "model_checksums": dict(self._checksums),
            "requires_network": False,
            "sends_data_external": False,
            "local_files_only": True,
            "supports_vision": self.supports_vision,
            "supports_pdf": self.supports_pdf,
            "supports_structured_output": self.supports_json_schema_output,
            "license": safe_config.get("license", "varies — see model card"),
            "enabled_by_default": False,
            "safe_for_export_decision": False,
            "safe_for_image_redaction": False,
            "hf_offline_env": dict(HF_OFFLINE_ENV),
            "config": safe_config,
        }

    @staticmethod
    def _compute_checksums(model_dir: Path) -> dict[str, str]:
        checksums: dict[str, str] = {}
        for f in sorted(model_dir.rglob("*")):
            if not f.is_file():
                continue
            try:
                h = hashlib.sha256()
                with f.open("rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        h.update(chunk)
                checksums[str(f.relative_to(model_dir))] = h.hexdigest()
            except OSError:  # pragma: no cover
                continue
        return checksums
