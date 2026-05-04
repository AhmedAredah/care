"""Microsoft Presidio provider skeleton.

Loads only from a local ``model_dir``. Sets the Hugging Face /
Transformers offline environment variables so that the underlying
spaCy / transformers model load cannot reach the network. Refuses to
start if the model directory is missing or if the configuration tries
to enable network access.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from ...core.constants import HF_OFFLINE_ENV
from ...core.errors import ConfigError, OfflineGuardError
from ...ocr.base import ProviderHealth
from ..base import PIIDetectionProvider
from ..entities import PIIEntity

_log = logging.getLogger(__name__)


class PresidioPIIProvider(PIIDetectionProvider):
    name = "presidio"
    version = "0.1.0"
    provider_type = "pii_detector"
    requires_network = False
    enabled_by_default = False

    MODEL_DIR_KEYS = ("model_dir",)
    WEIGHT_MARKERS = ("config.json",)

    supported_entities = [
        "PERSON_NAME",
        "EMAIL",
        "PHONE_NUMBER",
        "LOCATION",
        "DATE_OF_BIRTH",
        "VIN",
    ]
    supports_offsets = True
    supports_bboxes = False
    supports_confidence = True

    def __init__(self) -> None:
        self._loaded = False
        self._model_dir: Optional[Path] = None
        self._analyzer: Any = None

    def load(self, config: dict[str, Any]) -> None:
        if config.get("allow_network", False):
            raise ConfigError(
                "presidio.allow_network must be false"
            )
        if not config.get("local_files_only", True):
            raise ConfigError("presidio.local_files_only must be true")

        model_dir = Path(config.get("model_dir") or "")
        if not model_dir or not model_dir.exists():
            raise OfflineGuardError(
                f"Presidio model_dir not found at {model_dir!s}; refusing "
                "to start in offline mode."
            )
        self._model_dir = model_dir

        # Make sure HF env vars are set even if the global offline guard
        # was not enabled before this provider loads.
        for key, value in HF_OFFLINE_ENV.items():
            os.environ.setdefault(key, value)

        try:
            import presidio_analyzer  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ConfigError(
                "presidio_analyzer is not installed. Install via offline "
                "wheelhouse before enabling this provider."
            ) from exc

        # Real loader call goes here. Skipped from CI coverage — model
        # files are not committed.
        self._analyzer = presidio_analyzer.AnalyzerEngine()  # pragma: no cover
        self._loaded = True

    def detect_text(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> list[PIIEntity]:
        if not self._loaded:
            raise RuntimeError("PresidioPIIProvider.load() must be called first")
        # Real implementation calls ``self._analyzer.analyze(text=text, ...)``
        # and converts the result into PIIEntity. Out of scope for Phase 5.
        raise NotImplementedError(  # pragma: no cover
            "Real Presidio execution is exercised by Phase 7 packaging tests."
        )

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=self._loaded,
            detail=f"model_dir={self._model_dir}" if self._loaded else "not loaded",
        )

    def get_model_manifest(self) -> dict[str, Any]:
        return {
            "provider_name": self.name,
            "provider_version": self.version,
            "provider_type": self.provider_type,
            "model_name": "presidio-analyzer",
            "model_version": "local",
            "model_path": str(self._model_dir) if self._model_dir else None,
            "model_checksums": {},
            "license": "MIT",
            "requires_network": False,
            "enabled_by_default": self.enabled_by_default,
            "safe_for_offline_use": True,
            "supported_entities": list(self.supported_entities),
        }
