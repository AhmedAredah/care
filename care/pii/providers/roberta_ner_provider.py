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
- ``allow_network=true`` and ``local_files_only=false`` rejected at load.
- Hugging Face offline env vars re-applied on every load.
- Fails closed on missing or incomplete model_dir.
- Per-file SHA-256 checksums on the manifest.
- License is **MIT** — no review-required flag (unlike Piiranha).
- Inference exceptions absorbed; provider returns ``[]``.
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
from ..base import PIIDetectionProvider
from ..entities import ENTITY_TYPES, PIIEntity

_log = logging.getLogger(__name__)

# Default mapping. ORG and MISC drop by default — they're rarely PII
# in a crash-report context. Operators that want to redact org names
# (e.g., for HIPAA-style hospital scrubbing) can set:
#   pii.providers.roberta_ner.label_map.ORG: VEHICLE_OWNER_INFO
DEFAULT_LABEL_MAP: dict[str, Optional[str]] = {
    "PER": "PERSON_NAME",
    "LOC": "ADDRESS",
    "ORG": None,
    "MISC": None,
}

_REQUIRED_MODEL_FILES: tuple[str, ...] = ("config.json",)


class RobertaNERProvider(PIIDetectionProvider):
    name = "roberta_ner"
    version = "0.1.0"
    provider_type = "pii_detector"
    requires_network = False
    enabled_by_default = False

    MODEL_DIR_KEYS = ("model_dir",)
    WEIGHT_MARKERS = _REQUIRED_MODEL_FILES

    supported_entities = ["PERSON_NAME", "ADDRESS"]
    supports_offsets = True
    supports_bboxes = False
    supports_confidence = True

    def __init__(self) -> None:
        self._loaded = False
        self._model_dir: Optional[Path] = None
        self._pipeline: Any = None
        self._label_map: dict[str, Optional[str]] = dict(DEFAULT_LABEL_MAP)
        self._min_confidence: float = 0.85
        self._aggregation_strategy: str = "simple"
        self._checksums: dict[str, str] = {}
        self._last_raw_spans: list[dict[str, Any]] = []

    # ----- lifecycle --------------------------------------------------

    def load(self, config: dict[str, Any]) -> None:
        if config.get("allow_network", False):
            raise ConfigError(
                "roberta_ner.allow_network must be false"
            )
        if not config.get("local_files_only", True):
            raise ConfigError("roberta_ner.local_files_only must be true")

        model_dir = Path(config.get("model_dir") or "")
        if not str(model_dir) or not model_dir.exists():
            raise OfflineGuardError(
                f"roberta_ner model_dir not found at {model_dir!s}; refusing "
                "to start in offline mode."
            )
        missing = [
            f for f in _REQUIRED_MODEL_FILES if not (model_dir / f).exists()
        ]
        if missing:
            raise OfflineGuardError(
                f"roberta_ner model_dir is incomplete at {model_dir!s}: "
                f"missing {missing}."
            )

        for key, value in HF_OFFLINE_ENV.items():
            os.environ[key] = value

        # Operator-supplied label_map merges over default; values may
        # be None (drop) or any string in ENTITY_TYPES.
        custom_map = config.get("label_map") or {}
        if not isinstance(custom_map, dict):
            raise ConfigError("roberta_ner.label_map must be a dict if set")
        merged_map: dict[str, Optional[str]] = dict(DEFAULT_LABEL_MAP)
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
        self._label_map = merged_map

        min_conf = float(config.get("min_confidence", 0.85))
        if not (0.0 <= min_conf <= 1.0):
            raise ConfigError("roberta_ner.min_confidence must be in [0.0, 1.0]")
        self._min_confidence = min_conf

        agg = str(config.get("aggregation_strategy", "simple"))
        if agg not in {"none", "simple", "first", "average", "max"}:
            raise ConfigError(
                f"roberta_ner.aggregation_strategy={agg!r} not recognised"
            )
        self._aggregation_strategy = agg

        self._model_dir = model_dir
        self._checksums = self._compute_checksums(model_dir)
        self._pipeline = self._build_pipeline(model_dir, aggregation_strategy=agg)
        self._loaded = True

    @staticmethod
    def _build_pipeline(
        model_dir: Path, *, aggregation_strategy: str = "simple"
    ) -> Any:
        try:
            from transformers import (  # type: ignore[import-not-found]
                AutoModelForTokenClassification,
                AutoTokenizer,
                pipeline as hf_pipeline,
            )
        except ImportError as exc:
            raise ConfigError(
                "transformers is not installed. Install via wheelhouse "
                "before enabling roberta_ner."
            ) from exc
        tokenizer = AutoTokenizer.from_pretrained(
            str(model_dir), local_files_only=True
        )
        model = AutoModelForTokenClassification.from_pretrained(
            str(model_dir), local_files_only=True
        )
        return hf_pipeline(
            "token-classification",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy=aggregation_strategy,
        )

    # ----- inference --------------------------------------------------

    def detect_text(
        self,
        text: str,
        context: dict[str, Any] | None = None,
    ) -> list[PIIEntity]:
        if not self._loaded or self._pipeline is None:
            raise RuntimeError("RobertaNERProvider.load() must be called first")
        if not text or not text.strip():
            self._last_raw_spans = []
            return []
        try:
            raw = self._pipeline(text)
        except Exception as exc:  # noqa: BLE001
            _log.warning("roberta_ner inference failed: %s", type(exc).__name__)
            self._last_raw_spans = []
            return []
        self._last_raw_spans = [
            {
                "label": str(s.get("entity_group") or s.get("entity") or ""),
                "score": float(s.get("score", 0.0)),
                "word": str(s.get("word") or ""),
                "start": s.get("start"),
                "end": s.get("end"),
            }
            for s in (raw or [])
        ]

        entities: list[PIIEntity] = []
        for span in raw or []:
            label = self._extract_label(span)
            if not label:
                continue
            mapped = self._label_map.get(label.upper(), None)
            if mapped is None:
                # Operator-configured drop (or default behavior for ORG/MISC).
                continue
            score = float(span.get("score", 0.0))
            if score < self._min_confidence:
                continue
            start = span.get("start")
            end = span.get("end")
            word = span.get("word") or ""
            if start is None or end is None or end <= start:
                entities.append(
                    PIIEntity(
                        entity_type=mapped,
                        text=str(word),
                        start_offset=None,
                        end_offset=None,
                        confidence=score,
                        provider=self.name,
                        detection_reason=f"roberta_ner:{label}",
                        requires_review=True,
                        sources=[self.name],
                    )
                )
                continue
            entities.append(
                PIIEntity(
                    entity_type=mapped,
                    text=text[start:end],
                    start_offset=int(start),
                    end_offset=int(end),
                    confidence=score,
                    provider=self.name,
                    detection_reason=f"roberta_ner:{label}",
                    requires_review=True,
                    sources=[self.name],
                )
            )
        return entities

    @staticmethod
    def _extract_label(span: dict[str, Any]) -> str:
        """Return the label, stripping any ``B-`` / ``I-`` prefix.

        Jean-Baptiste/roberta-large-ner-english publishes labels
        without prefixes (``PER`` / ``LOC`` / ``ORG`` / ``MISC``)
        but we strip prefixes anyway in case the operator is using
        a different CoNLL-2003-style checkpoint that retained them.
        """
        raw = span.get("entity_group") or span.get("entity") or ""
        raw = str(raw)
        if raw[:2] in ("B-", "I-"):
            return raw[2:]
        return raw

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

    # ----- helpers ---------------------------------------------------

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
