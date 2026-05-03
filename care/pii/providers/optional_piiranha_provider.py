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
   placeholder — recall over precision per CONTRACT §PII Plugin
   Interface).
4. Emits one :class:`PIIEntity` per merged span with offsets,
   confidence, ``provider="piiranha"``, and ``requires_review=True``.

Safety
------
- Refuses ``allow_network=true`` and ``local_files_only=false``.
- Re-applies ``HF_OFFLINE_ENV`` on every load.
- Fails closed on missing model files.
- Per-file SHA-256 checksums recorded on the manifest for tamper
  detection.
- Never logs raw text; only counts and entity types.
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

# Minimum set of files we require under model_dir before attempting
# any transformers load. ``config.json`` alone is sufficient to fail
# closed with a clear message — without it, the HF AutoTokenizer call
# raises a far less actionable error.
_REQUIRED_MODEL_FILES: tuple[str, ...] = ("config.json",)


class PiiranhaPIIProvider(PIIDetectionProvider):
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

    def __init__(self) -> None:
        self._loaded = False
        self._model_dir: Optional[Path] = None
        self._pipeline: Any = None
        self._label_map: dict[str, str] = dict(DEFAULT_LABEL_MAP)
        self._min_confidence: float = 0.4
        self._aggregation_strategy: str = "simple"
        self._checksums: dict[str, str] = {}
        self._last_raw_spans: list[dict[str, Any]] = []

    # ----- lifecycle --------------------------------------------------

    def load(self, config: dict[str, Any]) -> None:
        if config.get("allow_network", False):
            raise ConfigError(
                "piiranha.allow_network must be false"
            )
        if not config.get("local_files_only", True):
            raise ConfigError("piiranha.local_files_only must be true")

        _log.warning(LICENSE_WARNING)
        if "license_warning" in config:
            _log.warning("Piiranha config license note: %s", config["license_warning"])

        model_dir = Path(config.get("model_dir") or "")
        if not str(model_dir) or not model_dir.exists():
            raise OfflineGuardError(
                f"Piiranha model_dir not found at {model_dir!s}; refusing "
                "to start in offline mode."
            )
        missing = [
            f for f in _REQUIRED_MODEL_FILES if not (model_dir / f).exists()
        ]
        if missing:
            raise OfflineGuardError(
                f"Piiranha model_dir is incomplete at {model_dir!s}: missing "
                f"{missing}. Place the local checkpoint files there before "
                "enabling the plugin."
            )

        for key, value in HF_OFFLINE_ENV.items():
            os.environ[key] = value

        # Operator-supplied label_map merges over the default. We never
        # let the operator REMOVE a label by omission; only override
        # what they explicitly set.
        custom_map = config.get("label_map") or {}
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
        self._label_map = merged_map

        min_conf = float(config.get("min_confidence", 0.4))
        if not (0.0 <= min_conf <= 1.0):
            raise ConfigError("piiranha.min_confidence must be in [0.0, 1.0]")
        self._min_confidence = min_conf

        agg = str(config.get("aggregation_strategy", "simple"))
        if agg not in {"none", "simple", "first", "average", "max"}:
            raise ConfigError(
                f"piiranha.aggregation_strategy={agg!r} not recognised "
                "(expected: none, simple, first, average, max)"
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
        """Construct the HF token-classification pipeline.

        Factored out so tests can monkeypatch a fake pipeline without
        touching ``transformers``. ``aggregation_strategy`` merges
        sub-token pieces into one entity per span — that's what gives
        us word-level offsets to use for redaction.
        """
        try:
            from transformers import (  # type: ignore[import-not-found]
                AutoModelForTokenClassification,
                AutoTokenizer,
                pipeline as hf_pipeline,
            )
        except ImportError as exc:
            raise ConfigError(
                "transformers is not installed. Install via offline "
                "wheelhouse before enabling Piiranha."
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
            raise RuntimeError("PiiranhaPIIProvider.load() must be called first")
        if not text or not text.strip():
            self._last_raw_spans = []
            return []
        try:
            raw = self._pipeline(text)
        except Exception as exc:  # noqa: BLE001 — provider failure must not crash pipeline
            _log.warning("piiranha inference failed: %s", type(exc).__name__)
            self._last_raw_spans = []
            return []
        # Snapshot the raw pipeline output for debug surfaces. Stored
        # without text content beyond what the operator-supplied
        # input already contains. We never log this; only the CLI
        # exposes it when --show-raw is set.
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
            mapped = self._label_map.get(label.upper(), _FALLBACK_ENTITY_TYPE)
            score = float(span.get("score", 0.0))
            if score < self._min_confidence:
                continue
            start = span.get("start")
            end = span.get("end")
            word = span.get("word") or ""
            if start is None or end is None or end <= start:
                # Pipeline returned a span without offsets — emit it
                # for the redactor to look up by text, but flag it.
                entities.append(
                    PIIEntity(
                        entity_type=mapped,
                        text=str(word),
                        start_offset=None,
                        end_offset=None,
                        confidence=score,
                        provider=self.name,
                        detection_reason=f"piiranha:{label}",
                        requires_review=True,
                        sources=[self.name],
                    )
                )
                continue
            extracted = text[start:end]
            entities.append(
                PIIEntity(
                    entity_type=mapped,
                    text=extracted,
                    start_offset=int(start),
                    end_offset=int(end),
                    confidence=score,
                    provider=self.name,
                    detection_reason=f"piiranha:{label}",
                    requires_review=True,
                    sources=[self.name],
                )
            )
        return entities

    @staticmethod
    def _extract_label(span: dict[str, Any]) -> str:
        """Return the bare label (no ``B-`` / ``I-`` prefix).

        HF pipelines vary on whether the prefix is included and on
        the field name (``entity`` vs ``entity_group``). We accept
        either to keep this resilient across transformers versions.
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
