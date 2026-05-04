"""RoBERTa-large NER provider (general English NER).

Wraps ``Jean-Baptiste/roberta-large-ner-english`` (or any
CoNLL-2003-style ``PER`` / ``LOC`` / ``ORG`` / ``MISC`` token-
classification checkpoint). Disabled by default. Loads only from a
local ``model_dir``.

This is a SUPPLEMENTARY recognizer in the PII chain — it catches
free-text named entities (people, places, organisations) that the
regex providers can't reliably detect, while regex providers remain
primary for structured PII (phone numbers, emails, SSNs, VINs, etc.)
that the NER model wasn't trained to flag.

Default label mapping (operator-overridable via ``config["label_map"]``):

- ``PER`` → ``PERSON_NAME``
- ``LOC`` → ``ADDRESS`` (cities/states; street numbers stay regex-driven)
- ``ORG`` → dropped by default (org names on a crash report — DOT,
  insurer, hospital — are typically not PII the operator wants
  redacted; configurable per deployment)
- ``MISC`` → dropped (too vague to map safely)

Safety
------
- ``allow_network=true`` and ``local_files_only=false`` rejected at load
  (via :meth:`PIIDetectionProvider.assert_offline_config`).
- Hugging Face offline env vars re-applied on every load.
- Fails closed on missing or incomplete model_dir.
- Per-file SHA-256 checksums on the manifest.
- License is **MIT** — no review-required flag (unlike Piiranha).
- Inference exceptions absorbed; provider returns ``[]``.

Most of the HF lifecycle lives on
:class:`HFTokenClassificationMixin`. This provider only owns the
roberta-specific policy: a label map that may DROP labels (None
values), a higher default ``min_confidence``, and the manifest.
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

# Default mapping. ORG and MISC drop by default — they're rarely PII
# in a crash-report context. Operators that want to redact org names
# (e.g., for HIPAA-style hospital scrubbing) can set:
#   pii.providers.roberta_ner.label_map.ORG: VEHICLE_OWNER_INFO
DEFAULT_LABEL_MAP: dict[str, str | None] = {
    "PER": "PERSON_NAME",
    "LOC": "ADDRESS",
    "ORG": None,
    "MISC": None,
}


class RobertaNERProvider(HFTokenClassificationMixin, PIIDetectionProvider):
    name = "roberta_ner"
    version = "0.1.0"
    provider_type = "pii_detector"
    requires_network = False
    enabled_by_default = False

    MODEL_DIR_KEYS = ("model_dir",)
    WEIGHT_MARKERS = HFTokenClassificationMixin.REQUIRED_MODEL_FILES

    supported_entities = ["PERSON_NAME", "ADDRESS"]
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

        model_dir = self._validate_model_dir(config, name="roberta_ner")
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
        """Operator-supplied ``label_map`` merges over default; values
        may be ``None`` (drop) or any string in ``ENTITY_TYPES``."""
        if not isinstance(custom_map, dict):
            raise ConfigError("roberta_ner.label_map must be a dict if set")
        merged_map: dict[str, str | None] = dict(DEFAULT_LABEL_MAP)
        for k, v in custom_map.items():
            key = str(k).upper()
            if v is None:
                merged_map[key] = None
                continue
            if not isinstance(v, str) or v not in ENTITY_TYPES:
                raise ConfigError(
                    f"roberta_ner.label_map[{k!r}]={v!r} is not in the "
                    f"canonical ENTITY_TYPES vocabulary (or None to drop)"
                )
            merged_map[key] = v
        return merged_map

    # ----- inference --------------------------------------------------

    def detect_text(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> list[PIIEntity]:
        return self._run_inference(text)

    def _map_label(self, label: str) -> str | None:
        """RoBERTa's policy: a label that the merged map points at
        ``None`` is dropped (default behavior for ORG/MISC). Unknown
        labels are also dropped — the NER head produces only four
        classes, so anything outside them is a transformers
        version artefact."""
        return self._label_map.get(label.upper(), None)

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
            "model_name": "roberta-large-ner-english",
            "model_version": "local",
            "model_path": str(self._model_dir) if self._model_dir else None,
            "model_checksums": dict(self._checksums),
            "license": "MIT",
            "requires_network": False,
            "enabled_by_default": False,
            "safe_for_offline_use": True,
            "supported_entities": list(self.supported_entities),
            "label_map": {k: v for k, v in self._label_map.items()},
            "min_confidence": self._min_confidence,
            "aggregation_strategy": self._aggregation_strategy,
            "hf_offline_env": dict(HF_OFFLINE_ENV),
        }
