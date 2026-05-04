"""OpenAI Privacy Filter PII provider.

Wraps ``openai/privacy-filter`` (Apache-2.0). A bidirectional
token-classification model trained for high-throughput PII detection
and masking, added to HF Transformers in v5.6.0 as
:class:`OpenAIPrivacyFilterForTokenClassification`. Loads via the
standard ``pipeline("token-classification", ...)`` path — no
``trust_remote_code`` and no custom decoder code in the provider (the
model's optional Viterbi calibration is left for a future enhancement).

Disabled by default. Loads only from a local ``model_dir``.

Supplements the regex chain on free-text PII the regex recognizers
can't reliably catch (free-form addresses, account numbers in
narrative prose, miscellaneous secret-shaped strings). Regex stays
primary for structured PII (phone, email, SSN, VIN, etc.) where its
recall already matches or exceeds an ML model's.

Default label mapping (operator-overridable via ``config["label_map"]``):

- ``private_person`` → ``PERSON_NAME``
- ``private_address`` → ``ADDRESS``
- ``private_email`` → ``EMAIL``
- ``private_phone`` → ``PHONE_NUMBER``
- ``private_date`` → ``DATE_OF_BIRTH`` (DOB is the relevant date PII
  on a crash report; report_date / crash_date are not PII)
- ``account_number`` → ``INSURANCE_POLICY`` (insurance-policy / claim
  numbers dominate this field on crash reports; configurable)
- ``secret`` → ``CASE_NUMBER`` (catch-all for passwords, tokens, ID
  numbers — recall over precision)
- ``private_url`` → dropped by default (URLs in crash reports are
  typically external refs — DOT websites, court systems — not PII;
  operators can opt in via ``label_map``)

Safety
------
- ``allow_network=true`` and ``local_files_only=false`` rejected at
  load (via :meth:`PIIDetectionProvider.assert_offline_config`).
- Hugging Face offline env vars re-applied on every load.
- Fails closed on missing or incomplete model_dir.
- Per-file SHA-256 checksums on the manifest.
- License is **Apache-2.0** — commercial use allowed; no
  ``license_review_required`` flag (unlike Piiranha).
- Inference exceptions absorbed; provider returns ``[]``.

Most of the HF lifecycle lives on
:class:`HFTokenClassificationMixin`. This provider only owns the
privacy-filter-specific policy: a label map that may DROP labels
(None values) and the manifest payload.
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

# Default mapping. Label keys match the model's lowercase output (no
# BIOES prefix — the HF pipeline strips those at aggregation time, and
# the mixin's ``_extract_label`` strips them defensively if the
# pipeline returns them anyway).
DEFAULT_LABEL_MAP: dict[str, str | None] = {
    "private_person": "PERSON_NAME",
    "private_address": "ADDRESS",
    "private_email": "EMAIL",
    "private_phone": "PHONE_NUMBER",
    "private_date": "DATE_OF_BIRTH",
    "account_number": "INSURANCE_POLICY",
    "secret": "CASE_NUMBER",
    "private_url": None,
}


class OpenAIPrivacyFilterProvider(HFTokenClassificationMixin, PIIDetectionProvider):
    name = "openai_privacy_filter"
    version = "0.1.0"
    provider_type = "pii_detector"
    requires_network = False
    enabled_by_default = False

    MODEL_DIR_KEYS = ("model_dir",)
    WEIGHT_MARKERS = HFTokenClassificationMixin.REQUIRED_MODEL_FILES

    # Reflects the non-None values of DEFAULT_LABEL_MAP. Sorted so the
    # manifest stays stable across runs.
    supported_entities = sorted(
        {v for v in DEFAULT_LABEL_MAP.values() if v is not None}
    )
    supports_offsets = True
    supports_bboxes = False
    supports_confidence = True

    def __init__(self) -> None:
        self._loaded = False
        self._model_dir: Path | None = None
        self._pipeline: Any = None
        self._label_map: dict[str, str | None] = dict(DEFAULT_LABEL_MAP)
        self._min_confidence: float = 0.85
        self._aggregation_strategy: str = "simple"
        self._checksums: dict[str, str] = {}
        self._last_raw_spans: list[dict[str, Any]] = []

    # ----- lifecycle --------------------------------------------------

    def load(self, config: dict[str, Any]) -> None:
        self.assert_offline_config(config)

        model_dir = self._validate_model_dir(config, name="openai_privacy_filter")
        self._apply_offline_env()
        self._label_map = self._merge_label_map(config.get("label_map") or {})
        self._min_confidence = self._validate_min_confidence(
            float(config.get("min_confidence", 0.85)), name=self.name
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
    def _merge_label_map(custom_map: Any) -> dict[str, str | None]:
        """Operator-supplied ``label_map`` merges over the default.

        Keys are normalised to lowercase to match the model's output
        labels. Values may be ``None`` (drop) or any string in
        :data:`ENTITY_TYPES`. We never let the operator REMOVE a
        default key by omission — only override what they explicitly
        set.
        """
        if not isinstance(custom_map, dict):
            raise ConfigError(
                "openai_privacy_filter.label_map must be a dict if set"
            )
        merged: dict[str, str | None] = dict(DEFAULT_LABEL_MAP)
        for k, v in custom_map.items():
            key = str(k).lower()
            if v is None:
                merged[key] = None
                continue
            if not isinstance(v, str) or v not in ENTITY_TYPES:
                raise ConfigError(
                    f"openai_privacy_filter.label_map[{k!r}]={v!r} is not in "
                    f"the canonical ENTITY_TYPES vocabulary (or None to drop)"
                )
            merged[key] = v
        return merged

    # ----- inference --------------------------------------------------

    def detect_text(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> list[PIIEntity]:
        return self._run_inference(text)

    def _map_label(self, label: str) -> str | None:
        """Privacy-filter emits eight known lowercase labels. Map via
        ``self._label_map``; ``None`` drops the span. Anything outside
        the eight (a transformers version artefact, or a custom
        fine-tune that introduced new labels) is also dropped."""
        return self._label_map.get(label.lower(), None)

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
            "model_name": "openai-privacy-filter",
            "model_version": "local",
            "model_path": str(self._model_dir) if self._model_dir else None,
            "model_checksums": dict(self._checksums),
            "license": "Apache-2.0",
            "requires_network": False,
            "enabled_by_default": False,
            "safe_for_offline_use": True,
            "supported_entities": list(self.supported_entities),
            "label_map": dict(self._label_map),
            "min_confidence": self._min_confidence,
            "aggregation_strategy": self._aggregation_strategy,
            "hf_offline_env": dict(HF_OFFLINE_ENV),
        }
