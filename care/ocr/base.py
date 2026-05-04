"""OCR plugin interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ..core.plugin_helpers import (
    assert_offline_config as _assert_offline_config,
    evaluate_model_files_present,
)
from .result import OCRResult


@dataclass
class ProviderHealth:
    healthy: bool
    detail: str = ""


class OCRProvider(ABC):
    name: str = ""
    version: str = ""
    provider_type: str = "traditional_ocr"
    requires_network: bool = False
    enabled_by_default: bool = False

    supports_pdf: bool = False
    supports_image: bool = True
    supports_word_bboxes: bool = False
    supports_line_bboxes: bool = False
    supports_confidence: bool = False

    # Subclasses override these to declare which config keys point at
    # model directories and which filenames/globs identify a populated
    # install. The default empty tuples mean "no model files needed"
    # (pure-Python or no-op providers).
    MODEL_DIR_KEYS: tuple[str, ...] = ()
    WEIGHT_MARKERS: tuple[str, ...] = ()

    # Optional benchmark numbers surfaced in the GUI plugin picker.
    # Schema: {"tier": "A"|"B"|"C", "benchmark": str, "benchmark_version": str,
    #          "metric_name": "cer"|"wer"|"f1"|"accuracy", "headline": float,
    #          "per_entity": dict[str, float] | None, "notes": str | None}.
    # Tier A = project-run benchmark on a held-out crash-report corpus;
    # B = published numbers in-domain; C = vendor / unverified. The UI
    # only ranks providers within the same tier.
    accuracy_metrics: Optional[dict[str, Any]] = None

    @classmethod
    def assert_offline_config(cls, config: dict[str, Any]) -> None:
        """Reject any config that opts the provider into network access.

        Real OCR providers must call this as the first line of
        :meth:`load` so misconfiguration fails closed before model
        files are touched. The classmethod form picks up ``cls.name``
        for the error message automatically.
        """
        _assert_offline_config(cls.name, config)

    @classmethod
    def model_files_present(cls, provider_cfg: dict[str, Any]) -> Optional[bool]:
        return evaluate_model_files_present(
            provider_cfg,
            model_dir_keys=cls.MODEL_DIR_KEYS,
            weight_markers=cls.WEIGHT_MARKERS,
        )

    @abstractmethod
    def load(self, config: dict[str, Any]) -> None:
        """Initialize the provider from local-only config. Must not download anything."""

    @abstractmethod
    def process_page_image(self, image: Any, page_context: dict[str, Any]) -> OCRResult:
        """Run OCR on a single rendered page image."""

    @abstractmethod
    def healthcheck(self) -> ProviderHealth:
        """Cheap probe used by the registry and CLI to confirm the provider is usable."""

    @abstractmethod
    def get_model_manifest(self) -> dict[str, Any]:
        """Return a manifest entry: name, version, model_path, checksums, license, network requirement, etc."""

    def close(self) -> None:
        return None
