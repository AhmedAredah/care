"""Shared loader/inferencer for HF token-classification PII providers.

Both Piiranha and the RoBERTa-NER provider wrap a HuggingFace
``token-classification`` pipeline loaded from a local checkpoint.
Pre-mixin, they each carried ~110 lines of identical scaffolding —
filesystem checks, transformers loading, SHA-256 walks, B-/I- prefix
stripping, the inference exception/empty-text handling, and the
emit-PIIEntity loop. The only real divergences are:

- which raw labels map to which canonical entity types (each provider
  ships its own ``DEFAULT_LABEL_MAP`` and ``_map_label`` policy);
- whether unknown labels fall back to a sentinel type or get dropped;
- the default ``min_confidence`` threshold;
- the manifest payload (license, model_name, special flags);
- license-review side effects (Piiranha logs a warning on every load).

This module owns the mechanism. Concrete providers inherit
:class:`HFTokenClassificationMixin` alongside :class:`PIIDetectionProvider`
and override the small policy hooks below.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from ..core.errors import ConfigError, OfflineGuardError
from ..core.plugin_helpers import apply_hf_offline_env
from .entities import PIIEntity

_log = logging.getLogger(__name__)

_VALID_AGGREGATION_STRATEGIES: frozenset[str] = frozenset(
    {"none", "simple", "first", "average", "max"}
)


class HFTokenClassificationMixin:
    """Mixin that owns the HF-token-classification pipeline lifecycle.

    Concrete providers must:
    - Inherit from :class:`care.pii.base.PIIDetectionProvider` first,
      then this mixin (so the base provides ``self.name`` and
      ``self.assert_offline_config``).
    - Implement :meth:`_map_label` to translate raw HF labels to the
      project's canonical PII vocabulary (or ``None`` to drop).
    - Initialize ``self._pipeline``, ``self._loaded``,
      ``self._last_raw_spans``, and ``self._min_confidence`` in
      ``__init__`` (the mixin calls into them).
    """

    # Subclasses can override; ``config.json`` alone is enough to fail
    # closed with a clear message — without it, AutoTokenizer raises a
    # far less actionable error.
    REQUIRED_MODEL_FILES: tuple[str, ...] = ("config.json",)

    # ----- model-dir validation --------------------------------------

    def _validate_model_dir(self, config: dict[str, Any], *, name: str) -> Path:
        """Return the validated ``model_dir`` Path, or raise.

        Rejects missing dirs and dirs without the marker files in
        :attr:`REQUIRED_MODEL_FILES`. Caller (the provider's
        ``load()``) owns the ``name`` so error messages name the right
        plugin in chain configurations.
        """
        model_dir = Path(config.get("model_dir") or "")
        if not str(model_dir) or not model_dir.exists():
            raise OfflineGuardError(
                f"{name} model_dir not found at {model_dir!s}; refusing "
                "to start in offline mode."
            )
        missing = [
            f for f in self.REQUIRED_MODEL_FILES if not (model_dir / f).exists()
        ]
        if missing:
            raise OfflineGuardError(
                f"{name} model_dir is incomplete at {model_dir!s}: missing "
                f"{missing}."
            )
        return model_dir

    # ----- environment + config validation ---------------------------

    @staticmethod
    def _apply_offline_env() -> None:
        """Re-pin ``HF_HUB_OFFLINE`` / ``TRANSFORMERS_OFFLINE`` etc. on
        every load — guarantees the env state is right even if a
        previous test or CLI invocation left it misconfigured."""
        apply_hf_offline_env()

    @staticmethod
    def _validate_aggregation_strategy(value: str, *, name: str) -> str:
        if value not in _VALID_AGGREGATION_STRATEGIES:
            raise ConfigError(
                f"{name}.aggregation_strategy={value!r} not recognised "
                f"(expected: {sorted(_VALID_AGGREGATION_STRATEGIES)})"
            )
        return value

    @staticmethod
    def _validate_min_confidence(value: float, *, name: str) -> float:
        if not (0.0 <= value <= 1.0):
            raise ConfigError(f"{name}.min_confidence must be in [0.0, 1.0]")
        return value

    # ----- pipeline construction -------------------------------------

    @staticmethod
    def _build_pipeline(
        model_dir: Path, *, aggregation_strategy: str = "simple"
    ) -> Any:
        """Construct a HF ``token-classification`` pipeline from a
        local checkpoint. ``aggregation_strategy`` merges sub-token
        pieces into one entity per span (gives word-level offsets for
        redaction). Lazy-imports ``transformers`` so the load-time
        safety tests run even without the runtime dep installed."""
        try:
            from transformers import (  # type: ignore[import-not-found]
                AutoModelForTokenClassification,
                AutoTokenizer,
            )
            from transformers import (
                pipeline as hf_pipeline,
            )
        except ImportError as exc:
            raise ConfigError(
                "transformers is not installed. Install via offline "
                "wheelhouse before enabling this provider."
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

    # ----- checksums -------------------------------------------------

    @staticmethod
    def _compute_checksums(model_dir: Path) -> dict[str, str]:
        """Walk every file under ``model_dir`` and return its SHA-256.

        Surfaced on the model manifest for tamper detection; never
        logged. Quietly skips files that error on read (rare; e.g.,
        permission issues mid-walk) — the manifest will record what we
        could read."""
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

    # ----- inference -------------------------------------------------

    @staticmethod
    def _extract_label(span: dict[str, Any]) -> str:
        """Return the bare label, stripping any ``B-`` / ``I-`` prefix.

        HF pipelines vary on whether the prefix is included and on
        the field name (``entity`` vs ``entity_group``). We accept
        either to stay resilient across transformers versions."""
        raw = span.get("entity_group") or span.get("entity") or ""
        raw = str(raw)
        if raw[:2] in ("B-", "I-"):
            return raw[2:]
        return raw

    def _map_label(self, label: str) -> str | None:
        """Translate a raw HF label to the canonical PII entity type.

        Subclasses MUST override. Return ``None`` to drop the span;
        return a string in ``ENTITY_TYPES`` to emit it. Piiranha
        always returns a string (unknown labels fall back to a
        sentinel); RoBERTa-NER may return ``None`` for ORG / MISC."""
        raise NotImplementedError

    def _run_inference(self, text: str) -> list[PIIEntity]:
        """Run inference and return ``PIIEntity`` results.

        Owns the empty-text early return, exception absorption (so a
        bad span never crashes the pipeline), the ``_last_raw_spans``
        debug snapshot, and the emit loop. Calls :meth:`_map_label`
        per span — that's the single divergence point between
        Piiranha and RoBERTa-NER."""
        if not getattr(self, "_loaded", False) or self._pipeline is None:
            raise RuntimeError(
                f"{type(self).__name__}.load() must be called first"
            )
        if not text or not text.strip():
            self._last_raw_spans = []
            return []
        try:
            raw = self._pipeline(text)
        except Exception as exc:  # noqa: BLE001 — provider failure must not crash pipeline
            _log.warning(
                "%s inference failed: %s", self.name, type(exc).__name__
            )
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
            mapped = self._map_label(label)
            if mapped is None:
                continue
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
                        detection_reason=f"{self.name}:{label}",
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
                    detection_reason=f"{self.name}:{label}",
                    requires_review=True,
                    sources=[self.name],
                )
            )
        return entities
