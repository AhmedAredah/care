"""Kosmos-2.5 VLM/document-AI provider skeleton.

Disabled by default. Loads only from a local ``model_dir`` /
``processor_dir``. Sets the Hugging Face / Transformers offline
environment variables and forces ``local_files_only=True`` on every
``from_pretrained`` call. Records model_path and per-file checksums in
its manifest.

VLM output is *generative*; the manifest declares this and downstream
reconciliation enforces the rule that VLM-only text without bounding
boxes can never drive image redaction.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Optional

from ...core.constants import HF_OFFLINE_ENV
from ...core.errors import ConfigError, OfflineGuardError
from ...ocr.base import ProviderHealth
from ..base import DocumentAIProvider
from ..result import (
    DocumentAIResult,
    MarkdownResult,
    SpatialTextResult,
)

_log = logging.getLogger(__name__)


class Kosmos25Provider(DocumentAIProvider):
    name = "kosmos25"
    version = "0.1.0"
    provider_type = "vlm_document_parser"
    requires_network = False
    enabled_by_default = False

    supports_image_to_text = True
    supports_image_to_markdown = True
    supports_spatial_text = True
    supports_region_detection = False
    supports_question_answering = False
    supports_confidence = False

    generative_model = True
    hallucination_risk = True

    def __init__(self) -> None:
        self._loaded = False
        self._model_dir: Optional[Path] = None
        self._processor_dir: Optional[Path] = None
        self._device: str = "auto"
        self._dtype: str = "bfloat16"
        self._tasks: dict[str, bool] = {}
        self._model: Any = None
        self._processor: Any = None
        self._checksums: dict[str, str] = {}

    def load(self, config: dict[str, Any]) -> None:
        if config.get("allow_network", False):
            raise ConfigError(
                "kosmos25.allow_network must be false"
            )
        if not config.get("local_files_only", True):
            raise ConfigError("kosmos25.local_files_only must be true")

        # Every HF/Transformers plugin MUST set the offline env vars.
        # We set them here even if the global offline guard hasn't
        # already.
        for key, value in HF_OFFLINE_ENV.items():
            os.environ.setdefault(key, value)

        model_dir = Path(config.get("model_dir") or "")
        processor_dir = Path(config.get("processor_dir") or model_dir)
        if not model_dir or not model_dir.exists():
            raise OfflineGuardError(
                f"Kosmos-2.5 model_dir not found at {model_dir!s}; refusing "
                "to start in offline mode."
            )
        if not processor_dir.exists():
            raise OfflineGuardError(
                f"Kosmos-2.5 processor_dir not found at {processor_dir!s}; "
                "refusing to start in offline mode."
            )

        self._model_dir = model_dir
        self._processor_dir = processor_dir
        self._device = str(config.get("device", "auto"))
        self._dtype = str(config.get("dtype", "bfloat16"))
        self._tasks = dict(config.get("tasks") or {})
        self._checksums = self._compute_checksums(model_dir)

        try:
            import transformers  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as exc:
            raise ConfigError(
                "transformers is not installed. Install via offline "
                "wheelhouse before enabling Kosmos-2.5."
            ) from exc

        # Real loader call goes here, e.g.:
        #     self._processor = AutoProcessor.from_pretrained(
        #         str(processor_dir), local_files_only=True,
        #     )
        #     self._model = AutoModelForVision2Seq.from_pretrained(
        #         str(model_dir), local_files_only=True, torch_dtype=...,
        #     )
        # Skipped from CI coverage — model files are not committed.
        self._loaded = True

    def process_page_image(
        self, image: Any, page_context: dict[str, Any], task: str
    ) -> DocumentAIResult:
        if not self._loaded:
            raise RuntimeError("Kosmos25Provider.load() must be called first")
        raise NotImplementedError(  # pragma: no cover
            "Real Kosmos-2.5 execution is exercised by Phase 7 packaging tests."
        )

    def image_to_spatial_text(
        self, image: Any, page_context: dict[str, Any]
    ) -> SpatialTextResult:
        if not self._loaded:
            raise RuntimeError("Kosmos25Provider.load() must be called first")
        raise NotImplementedError(  # pragma: no cover
            "Real Kosmos-2.5 spatial OCR is exercised by Phase 7 packaging tests."
        )

    def image_to_markdown(
        self, image: Any, page_context: dict[str, Any]
    ) -> MarkdownResult:
        if not self._loaded:
            raise RuntimeError("Kosmos25Provider.load() must be called first")
        raise NotImplementedError(  # pragma: no cover
            "Real Kosmos-2.5 markdown is exercised by Phase 7 packaging tests."
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
            "model_name": "kosmos-2.5",
            "model_version": "local",
            "model_path": str(self._model_dir) if self._model_dir else None,
            "processor_path": str(self._processor_dir) if self._processor_dir else None,
            "model_checksums": dict(self._checksums),
            "license": "MIT or value from local manifest",
            "requires_network": False,
            "enabled_by_default": False,
            "safe_for_offline_use": True,
            "generative": True,
            "may_hallucinate": True,
            "provides_bboxes": True,
            "safe_for_image_redaction": False,
            "device": self._device,
            "dtype": self._dtype,
            "tasks": dict(self._tasks),
            "local_files_only": True,
            "hf_offline_env": dict(HF_OFFLINE_ENV),
        }

    @staticmethod
    def _compute_checksums(model_dir: Path) -> dict[str, str]:
        """Walk the model dir and SHA-256 every file. Returns relative paths."""
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
