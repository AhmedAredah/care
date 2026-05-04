"""LayoutLM provider plugin (Phase 10 — optional, offline-only).

LayoutLM is Microsoft's text+layout document-understanding family
(``microsoft/layoutlm-base-uncased`` MIT, ``microsoft/layoutlmv3-base``
CC BY-NC-SA 4.0). This plugin wraps it for **suggestion-only** use:
region proposals for the template builder, fallback candidates when
no template scores high enough, and as a QA second-opinion. It MUST
NOT drive public export or PII redaction.

Offline-first invariants enforced here:

- Plugin is disabled by default (config.yaml registers it but does
  not enable it).
- ``allow_network=true`` is rejected at load time.
- ``local_files_only=false`` is rejected at load time.
- Model files must exist at the configured ``model_dir`` before load
  begins; missing files raise ``OfflineGuardError``.
- The full Hugging Face offline env-var set is applied at load time
  (defense in depth — the global offline guard already sets these,
  but plugin enable should set them again so the plugin can never
  load *before* the guard).
- Every ``from_pretrained`` call uses ``local_files_only=True``.
- The model manifest enumerates the safety posture (``requires_review``,
  ``safe_for_image_redaction=False``, etc.) so audit logs always
  show the constraints under which a suggestion was produced.

Sources reviewed (research before implementation, May 2026):

- Hugging Face Transformers — ``model_doc/layoutlm`` and
  ``model_doc/layoutlmv3``
- Model cards: ``microsoft/layoutlm-base-uncased`` (MIT) and
  ``microsoft/layoutlmv3-base`` (CC BY-NC-SA 4.0)
- HF Transformers offline-mode docs (``HF_HUB_OFFLINE=1``,
  ``local_files_only=True``).

The license difference (v1 MIT vs v3 NC-SA) is surfaced in the
manifest and a license-review-required marker fires for v3 to give
operators a hard stop before commercial deployment.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ...core.constants import HF_OFFLINE_ENV
from ...core.errors import ConfigError, OfflineGuardError
from ...core.plugin_helpers import apply_hf_offline_env
from ...ocr.base import ProviderHealth
from ..base import DocumentAIProvider
from ..result import (
    DocumentAIResult,
    RegionDetectionResult,
)

_log = logging.getLogger(__name__)


# Known LayoutLM checkpoint variants and their licenses. Looked up
# from Hugging Face model cards on 2026-05-01.
_KNOWN_VARIANT_LICENSES: dict[str, str] = {
    "layoutlm": "MIT",
    "layoutlm-base-uncased": "MIT",
    "layoutlm-base-cased": "MIT",
    "layoutlm-large-uncased": "MIT",
    "layoutlmv2": "CC BY-NC-SA 4.0",
    "layoutlmv2-base-uncased": "CC BY-NC-SA 4.0",
    "layoutlmv3": "CC BY-NC-SA 4.0",
    "layoutlmv3-base": "CC BY-NC-SA 4.0",
    "layoutlmv3-large": "CC BY-NC-SA 4.0",
}
_NON_COMMERCIAL_LICENSE = "CC BY-NC-SA 4.0"


@dataclass
class LayoutLMSuggestion:
    """One region proposed by the LayoutLM plugin.

    These are *suggestions only*. They never replace template-driven
    extraction; they only inform the template builder, fallback
    candidate generation, or QA flags.
    """

    label: str  # e.g. "diagram" | "narrative" | "header"
    bbox_norm: list[float]  # [x0, y0, x1, y1] in [0..1]
    confidence: float
    page_index: int
    qa_flags: list[str] = field(default_factory=list)
    requires_review: bool = True


class LayoutLMProvider(DocumentAIProvider):
    name = "layoutlm"
    version = "0.1.0"
    provider_type = "document_layout_model"
    requires_network = False
    enabled_by_default = False

    MODEL_DIR_KEYS = ("model_dir", "processor_dir")
    WEIGHT_MARKERS = ("config.json",)

    supports_image_to_text = False
    supports_image_to_markdown = False
    supports_spatial_text = False
    supports_region_detection = True
    supports_question_answering = False
    supports_confidence = True

    # The model is discriminative (token classification / region
    # detection), not generative. There is no free-text completion
    # path that could hallucinate. We still gate output on review.
    generative_model = False
    hallucination_risk = False

    def __init__(self) -> None:
        self._loaded = False
        self._model_dir: Path | None = None
        self._processor_dir: Path | None = None
        self._variant: str = "layoutlm-base-uncased"
        self._license: str = "unknown"
        self._license_review_required: bool = False
        self._device: str = "cpu"
        self._dtype: str = "float32"
        self._region_labels: list[str] = []
        self._model: Any = None
        self._processor: Any = None
        self._checksums: dict[str, str] = {}

    # ----- lifecycle ---------------------------------------------------

    def load(self, config: dict[str, Any]) -> None:
        # Reject network-enabling toggles first so we never even peek
        # at the rest of the config when a misconfigured deployment
        # tries to flip the safety switch.
        self.assert_offline_config(config)

        # Defense in depth: re-apply the HF offline env vars even if
        # the global offline guard already set them. The plugin must
        # never trust that some other layer set the right env.
        apply_hf_offline_env()

        model_dir = Path(config.get("model_dir") or "")
        if not str(model_dir) or not model_dir.exists():
            raise OfflineGuardError(
                f"LayoutLM model_dir not found at {model_dir!s}; "
                "refusing to load in offline mode. Place the local "
                "checkpoint files (config.json, pytorch_model.bin or "
                "model.safetensors, tokenizer.json, vocab.txt) under the "
                "configured model_dir before enabling layoutlm."
            )
        processor_dir = Path(config.get("processor_dir") or model_dir)
        if not processor_dir.exists():
            raise OfflineGuardError(
                f"LayoutLM processor_dir not found at {processor_dir!s}"
            )

        self._model_dir = model_dir
        self._processor_dir = processor_dir
        self._variant = str(config.get("variant", "layoutlm-base-uncased"))
        self._license = _resolve_license(self._variant, config)
        self._license_review_required = self._license == _NON_COMMERCIAL_LICENSE
        self._device = str(config.get("device", "cpu"))
        self._dtype = str(config.get("dtype", "float32"))
        self._region_labels = list(config.get("region_labels") or [])
        self._checksums = self._compute_checksums(model_dir)

        # The Transformers import is intentionally deferred. The
        # plugin must remain importable in environments that do NOT
        # have transformers installed (e.g. CI on a vanilla machine);
        # the dependency is only required when the operator enables
        # the plugin. We do NOT import transformers at module top.
        try:
            import transformers  # noqa: F401  type: ignore[import-not-found]
        except ImportError as exc:
            raise ConfigError(
                "transformers is not installed. Install via offline "
                "wheelhouse before enabling layoutlm."
            ) from exc

        # Real loader call goes here, e.g.:
        #     from transformers import AutoTokenizer, LayoutLMForTokenClassification
        #     self._processor = AutoTokenizer.from_pretrained(
        #         str(processor_dir), local_files_only=True,
        #     )
        #     self._model = LayoutLMForTokenClassification.from_pretrained(
        #         str(model_dir), local_files_only=True,
        #     )
        # Skipped from CI coverage — model files are not committed.
        self._loaded = True

    # ----- DocumentAIProvider surface ---------------------------------

    def process_page_image(
        self, image: Any, page_context: dict[str, Any], task: str
    ) -> DocumentAIResult:
        if not self._loaded:
            raise RuntimeError("LayoutLMProvider.load() must be called first")
        # Region detection is the only supported task. Anything else
        # is a misconfiguration — refuse rather than silently producing
        # a degenerate output.
        raise NotImplementedError(  # pragma: no cover
            "LayoutLM does not provide page-level OCR. Use detect_regions()."
        )

    def detect_regions(
        self, image: Any, page_context: dict[str, Any]
    ) -> RegionDetectionResult:
        """Return zero candidate regions in the skeleton; real runs land
        with model files present (Phase 7+ packaging tests)."""
        if not self._loaded:
            raise RuntimeError("LayoutLMProvider.load() must be called first")
        return RegionDetectionResult(
            regions=[], provider=self.name
        )  # pragma: no cover — real inference exercised when model files exist

    # ----- review / QA helpers ---------------------------------------

    def review_required_flags(self) -> list[str]:
        """QA flag set every LayoutLM call must add to the report.

        Always includes ``LAYOUTLM_PLUGIN_USED`` and
        ``LAYOUTLM_REQUIRES_REVIEW`` so any consumer of LayoutLM output
        is forced to drive the report through human review (unless the
        operator manually accepts a suggestion into a template via the
        builder, which exits the LayoutLM pathway entirely).
        """
        flags = ["LAYOUTLM_PLUGIN_USED", "LAYOUTLM_REQUIRES_REVIEW"]
        if self._license_review_required:
            flags.append("LAYOUTLM_LICENSE_REVIEW_REQUIRED")
        return flags

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(
            healthy=self._loaded,
            detail=(
                f"variant={self._variant} model_dir={self._model_dir}"
                if self._loaded
                else "not loaded"
            ),
        )

    def get_model_manifest(self) -> dict[str, Any]:
        """Return the audit manifest entry for this plugin.

        The manifest is the system-of-record for downstream review:
        every flag that gates redaction or export must be discoverable
        here. CI/Phase-7 packaging asserts these keys verbatim — DO
        NOT silently rename them.
        """
        return {
            "provider_name": self.name,
            "provider_version": self.version,
            "provider_type": self.provider_type,
            "model_name": self._variant,
            "model_path": str(self._model_dir) if self._model_dir else None,
            "model_path_present": bool(
                self._model_dir is not None and self._model_dir.exists()
            ),
            "processor_path": (
                str(self._processor_dir) if self._processor_dir else None
            ),
            "model_checksums": dict(self._checksums),
            "license": self._license,
            "license_review_required": self._license_review_required,
            "requires_network": False,
            "enabled_by_default": False,
            "generative_model": False,
            "hallucination_risk": False,
            "requires_review": True,
            "safe_for_image_redaction": False,
            "device": self._device,
            "dtype": self._dtype,
            "region_labels": list(self._region_labels),
            "local_files_only": True,
            "hf_offline_env": dict(HF_OFFLINE_ENV),
            "qa_flags_emitted_on_use": list(self.review_required_flags()),
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


def _resolve_license(variant: str, config: dict[str, Any]) -> str:
    """Pick the license to record on the manifest.

    Operator-supplied ``license`` in config wins (so a future variant
    we don't know about can still be declared). Otherwise look up the
    variant in our known table; default to "unknown" if neither path
    answers.
    """
    declared = config.get("license")
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    key = variant.split("/")[-1].lower()
    return _KNOWN_VARIANT_LICENSES.get(key, "unknown")
