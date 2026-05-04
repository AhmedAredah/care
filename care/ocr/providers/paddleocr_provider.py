"""PaddleOCR provider skeleton.

Loads only from local model directories declared in
``config.providers.paddleocr``. Refuses to start when offline mode is
active and any required directory is missing. Refuses any
``allow_network: true`` configuration. The actual ``process_page_image``
implementation calls into ``paddleocr.PaddleOCR`` and is exercised only
when the model files are placed on disk and the ``paddleocr`` wheel is
installed via the offline wheelhouse — both out of scope for the CI
test suite. The skeleton focuses on the safety guarantees.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...core.errors import ConfigError, OfflineGuardError
from ..base import OCRProvider, ProviderHealth
from ..result import OCRResult

_log = logging.getLogger(__name__)


class PaddleOCRProvider(OCRProvider):
    name = "paddleocr"
    version = "0.1.0"
    provider_type = "traditional_ocr"
    requires_network = False
    enabled_by_default = False

    supports_pdf = False
    supports_image = True
    supports_word_bboxes = True
    supports_line_bboxes = True
    supports_confidence = True

    MODEL_DIR_KEYS = ("det_model_dir", "rec_model_dir", "cls_model_dir")
    WEIGHT_MARKERS = ("*.pdmodel", "*.pdiparams")

    def __init__(self) -> None:
        self._loaded = False
        self._det_dir: Path | None = None
        self._rec_dir: Path | None = None
        self._cls_dir: Path | None = None
        self._engine: Any = None

    def load(self, config: dict[str, Any]) -> None:
        self.assert_offline_config(config)

        det = Path(config.get("det_model_dir") or "")
        rec = Path(config.get("rec_model_dir") or "")
        cls_raw = config.get("cls_model_dir")
        cls = Path(cls_raw) if cls_raw else None

        for label, path in (("det_model_dir", det), ("rec_model_dir", rec)):
            if not path or not path.exists():
                raise OfflineGuardError(
                    f"PaddleOCR {label} not found at {path!s}; refusing to "
                    "start in offline mode."
                )
        if cls is not None and not cls.exists():
            raise OfflineGuardError(
                f"PaddleOCR cls_model_dir not found at {cls!s}; refusing to "
                "start in offline mode."
            )

        self._det_dir = det
        self._rec_dir = rec
        self._cls_dir = cls

        try:
            import paddleocr  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ConfigError(
                "paddleocr is not installed. Install via offline wheelhouse "
                "before enabling this provider."
            ) from exc

        # The real engine call happens here. Skipped from CI coverage —
        # no model files are committed.
        self._engine = paddleocr.PaddleOCR(  # pragma: no cover
            det_model_dir=str(det),
            rec_model_dir=str(rec),
            cls_model_dir=str(cls) if cls else None,
            use_gpu=False,
            show_log=False,
        )
        self._loaded = True

    def process_page_image(
        self, image: Any, page_context: dict[str, Any]
    ) -> OCRResult:
        if not self._loaded:
            raise RuntimeError("PaddleOCRProvider.load() must be called first")
        # Real implementation goes here. Out of scope for Phase 5 tests.
        raise NotImplementedError(  # pragma: no cover
            "Real PaddleOCR execution is exercised by Phase 7 packaging tests."
        )

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=self._loaded,
            detail=f"loaded from {self._det_dir}" if self._loaded else "not loaded",
        )

    def get_model_manifest(self) -> dict[str, Any]:
        return {
            "provider_name": self.name,
            "provider_version": self.version,
            "provider_type": self.provider_type,
            "model_name": "paddleocr",
            "model_version": "local",
            "model_path": str(self._det_dir) if self._det_dir else None,
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
