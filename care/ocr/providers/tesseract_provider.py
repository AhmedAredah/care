"""Tesseract provider skeleton.

Uses a local tesseract binary + local ``tessdata_dir``. Never downloads
language data. Like the PaddleOCR skeleton, the ``process_page_image``
path is exercised only with real binaries installed; the focus is the
load-time safety guarantees.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from ...core.errors import ConfigError, OfflineGuardError
from ..base import OCRProvider, ProviderHealth
from ..result import OCRResult

_log = logging.getLogger(__name__)


class TesseractProvider(OCRProvider):
    name = "tesseract"
    version = "0.1.0"
    provider_type = "traditional_ocr"
    requires_network = False
    enabled_by_default = False

    supports_pdf = False
    supports_image = True
    supports_word_bboxes = True
    supports_line_bboxes = True
    supports_confidence = True

    MODEL_DIR_KEYS = ("tessdata_dir",)
    WEIGHT_MARKERS = ("*.traineddata",)

    def __init__(self) -> None:
        self._loaded = False
        self._tessdata_dir: Optional[Path] = None
        self._binary: Optional[str] = None

    def load(self, config: dict[str, Any]) -> None:
        if config.get("allow_network", False):
            raise ConfigError(
                "tesseract.allow_network must be false"
            )

        tessdata = Path(config.get("tessdata_dir") or "")
        if not tessdata or not tessdata.exists():
            raise OfflineGuardError(
                f"Tesseract tessdata_dir not found at {tessdata!s}; refusing "
                "to start in offline mode."
            )
        self._tessdata_dir = tessdata

        binary = config.get("binary") or shutil.which("tesseract")
        if not binary:
            raise ConfigError(
                "tesseract binary not found on PATH and no `binary:` configured"
            )
        self._binary = str(binary)
        self._loaded = True

    def process_page_image(
        self, image: Any, page_context: dict[str, Any]
    ) -> OCRResult:
        if not self._loaded:
            raise RuntimeError("TesseractProvider.load() must be called first")
        # Real implementation would invoke ``tesseract`` via subprocess
        # with ``--tessdata-dir`` set to ``self._tessdata_dir`` and parse
        # the hOCR / TSV output. Out of scope for Phase 5 tests.
        raise NotImplementedError(  # pragma: no cover
            "Real Tesseract execution is exercised by Phase 7 packaging tests."
        )

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=self._loaded,
            detail=f"binary={self._binary}, tessdata={self._tessdata_dir}" if self._loaded else "not loaded",
        )

    def get_model_manifest(self) -> dict[str, Any]:
        return {
            "provider_name": self.name,
            "provider_version": self.version,
            "provider_type": self.provider_type,
            "model_name": "tesseract",
            "model_version": "local",
            "model_path": str(self._tessdata_dir) if self._tessdata_dir else None,
            "binary_path": self._binary,
            "model_checksums": {},
            "license": "Apache-2.0",
            "requires_network": False,
            "enabled_by_default": self.enabled_by_default,
            "safe_for_offline_use": True,
            "generative": False,
            "may_hallucinate": False,
            "provides_bboxes": True,
            "safe_for_image_redaction": True,
        }
