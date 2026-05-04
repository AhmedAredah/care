"""Piiranha PII provider (Phase 12.2 — real integration).

DISABLED BY DEFAULT. Loads only from a local ``model_dir``. Emits a
license-review warning every time it loads — DOTs must verify the
license before deployment.

Inputs/outputs
--------------
The provider wraps a Hugging Face token-classification pipeline. The
default Piiranha checkpoint
(``iiiorg/piiranha-v1-detect-personal-information``) produces labels
like ``I-GIVENNAME``, ``I-EMAIL``, ``I-TELEPHONENUM``, etc. The
provider:

1. Strips the ``B-`` / ``I-`` prefix.
2. Looks the label up in :data:`DEFAULT_LABEL_MAP` (operator-overridable
   via ``config["label_map"]``).
3. Routes unknown labels to ``CASE_NUMBER`` (a catch-all sensitive-id
   placeholder — recall over precision per GOVERNANCE.md §PII Plugin
   Interface).
4. Emits one :class:`PIIEntity` per merged span with offsets,
   confidence, ``provider="piiranha"``, and ``requires_review=True``.

Safety
------
- Refuses ``allow_network=true`` and ``local_files_only=false``
  (via :meth:`PIIDetectionProvider.assert_offline_config`).
- Re-applies ``HF_OFFLINE_ENV`` on every load.
- Fails closed on missing model files.
- Per-file SHA-256 checksums recorded on the manifest for tamper
  detection.
- Never logs raw text; only counts and entity types.

Most of the HF lifecycle (filesystem checks, transformers loading,
pipeline construction, inference loop) lives on
:class:`HFTokenClassificationMixin` so this provider only owns the
piiranha-specific policy: the label-map default, the unknown-label
fallback, and the license-review warning.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...core.constants import HF_OFFLINE_ENV
from ...core.errors import ConfigError
from ...ocr.base import ProviderHealth
from .._hf_token_classification import HFTokenClassificationMixin
from ..base import PIIDetectionProvider
from ..entities import ENTITY_TYPES, PIIEntity

_log = logging.getLogger(__name__)

LICENSE_WARNING = (
    "Piiranha is OPTIONAL and DISABLED BY DEFAULT. "
    "Verify its license is acceptable for your DOT deployment "
    "before relying on it."
)

# Default mapping from Piiranha's NER labels (with B-/I- prefixes
# stripped) to the project's canonical PII vocabulary. The mapping is
# deliberately conservative: anything we don't recognise drops to
# CASE_NUMBER (a generic sensitive-id type) so it still gets
# redacted — recall over precision.
DEFAULT_LABEL_MAP: dict[str, str] = {
    "GIVENNAME": "PERSON_NAME",
    "SURNAME": "PERSON_NAME",
    "USERNAME": "PERSON_NAME",
    "MIDDLENAME": "PERSON_NAME",
    "EMAIL": "EMAIL",
    "TELEPHONENUM": "PHONE_NUMBER",
    "DATEOFBIRTH": "DATE_OF_BIRTH",
    "STREET": "ADDRESS",
    "BUILDINGNUM": "ADDRESS",
    "CITY": "ADDRESS",
    "STATE": "ADDRESS",
    "ZIPCODE": "ADDRESS",
    "COUNTRY": "ADDRESS",
    "SOCIALNUM": "SSN",
    "DRIVERLICENSENUM": "DRIVER_LICENSE",
    "IDCARDNUM": "CASE_NUMBER",
    "PASSPORTNUM": "CASE_NUMBER",
    "TAXNUM": "CASE_NUMBER",
    "ACCOUNTNUM": "INSURANCE_POLICY",
    "CREDITCARDNUMBER": "CASE_NUMBER",
}
_FALLBACK_ENTITY_TYPE = "CASE_NUMBER"


class PiiranhaPIIProvider(HFTokenClassificationMixin, PIIDetectionProvider):
    name = "piiranha"
    version = "0.2.0"
    provider_type = "pii_detector"
    requires_network = False
    enabled_by_default = False
    # Surfaced by the /api/plugins endpoint so the GUI can warn the
    # operator before they wire this provider into the chain.
    license_review_required = True

    supported_entities = sorted(set(DEFAULT_LABEL_MAP.values()))
    supports_offsets = True
    supports_bboxes = False
    supports_confidence = True

    MODEL_DIR_KEYS = ("model_dir",)
    WEIGHT_MARKERS = HFTokenClassificationMixin.REQUIRED_MODEL_FILES

    def __init__(self) -> None:
        self._loaded = False
        self._model_dir: Path | None = None
        self._pipeline: Any = None
        self._label_map: dict[str, str] = dict(DEFAULT_LABEL_MAP)
        self._min_confidence: float = 0.4
        self._aggregation_strategy: str = "simple"
        self._checksums: dict[str, str] = {}
        self._last_raw_spans: list[dict[str, Any]] = []

    # ----- lifecycle --------------------------------------------------

    def load(self, config: dict[str, Any]) -> None:
        self.assert_offline_config(config)

        _log.warning(LICENSE_WARNING)
        if "license_warning" in config:
            _log.warning("Piiranha config license note: %s", config["license_warning"])

        model_dir = self._validate_model_dir(config, name="Piiranha")
        self._apply_offline_env()
        self._label_map = self._merge_label_map(config.get("label_map") or {})
        self._min_confidence = self._validate_min_confidence(
            float(config.get("min_confidence", 0.4)), name=self.name
        )
        self._aggregation_strategy = self._validate_aggregation_strategy(
            str(config.get("aggregation_strategy", "simple")), name=self.name
        )
        self._model_dir = model_dir
        self._checksums = self._compute_checksums(model_dir)
        self._pipeline = self._build_pipeline(
            model_dir, aggregation_strategy=self._aggregation_strategy
        )
        self._loaded = True

    @staticmethod
    def _merge_label_map(custom_map: Any) -> dict[str, str]:
        """Operator-supplied ``label_map`` merges over the default. We
        never let the operator REMOVE a label by omission; only override
        what they explicitly set. Values must be in the canonical
        ENTITY_TYPES vocabulary."""
        if not isinstance(custom_map, dict):
            raise ConfigError("piiranha.label_map must be a dict if set")
        merged_map = dict(DEFAULT_LABEL_MAP)
        for k, v in custom_map.items():
            if not isinstance(v, str) or v not in ENTITY_TYPES:
                raise ConfigError(
                    f"piiranha.label_map[{k!r}]={v!r} is not in the canonical "
                    f"ENTITY_TYPES vocabulary"
                )
            merged_map[str(k).upper()] = v
        return merged_map

    # ----- inference --------------------------------------------------

    def detect_text(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> list[PIIEntity]:
        return self._run_inference(text)

    def _map_label(self, label: str) -> str | None:
        """Piiranha's policy: unknown labels fall back to
        ``CASE_NUMBER`` rather than being dropped — recall over
        precision per GOVERNANCE.md §PII Plugin Interface."""
        return self._label_map.get(label.upper(), _FALLBACK_ENTITY_TYPE)

    # ----- introspection ---------------------------------------------

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
            "model_name": "piiranha",
            "model_version": "local",
            "model_path": str(self._model_dir) if self._model_dir else None,
            "model_checksums": dict(self._checksums),
            "license": "license-review-required",
            "requires_network": False,
            "enabled_by_default": False,
            "safe_for_offline_use": True,
            "supported_entities": list(self.supported_entities),
            "label_map": dict(self._label_map),
            "min_confidence": self._min_confidence,
            "requires_license_review_before_deployment": True,
            "hf_offline_env": dict(HF_OFFLINE_ENV),
        }
