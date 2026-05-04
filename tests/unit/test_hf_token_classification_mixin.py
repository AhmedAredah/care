"""``HFTokenClassificationMixin`` contract.

The mixin owns every piece of the HF-pipeline lifecycle that Piiranha
and RoBERTa-NER used to duplicate. Tests below pin the behaviour
that *both* providers used to verify themselves — moved here so a
future change can't silently shift one provider's behaviour relative
to the other.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from care.core.constants import HF_OFFLINE_ENV
from care.core.errors import ConfigError, OfflineGuardError
from care.pii._hf_token_classification import (
    _VALID_AGGREGATION_STRATEGIES,
    HFTokenClassificationMixin,
)
from care.pii.base import PIIDetectionProvider
from care.pii.entities import PIIEntity


class _FakePipeline:
    """Deterministic pipeline stand-in. Returns whatever ``spans`` was
    set at construction time when called."""

    def __init__(self, spans: list[dict[str, Any]]) -> None:
        self._spans = spans
        self.calls: list[str] = []

    def __call__(self, text: str) -> list[dict[str, Any]]:
        self.calls.append(text)
        return self._spans


class _FixtureProvider(HFTokenClassificationMixin, PIIDetectionProvider):
    """Minimal subclass used only by these tests. Drops every label
    except ``PER`` so the test surface is small and unambiguous."""

    name = "fixture"
    version = "0.0.0"
    provider_type = "pii_detector"

    def __init__(self) -> None:
        self._loaded = False
        self._pipeline: Any = None
        self._min_confidence: float = 0.0
        self._last_raw_spans: list[dict[str, Any]] = []

    def load(self, config: dict[str, Any]) -> None:  # pragma: no cover
        raise NotImplementedError

    def detect_text(
        self, text: str, context: dict[str, Any] | None = None
    ) -> list[PIIEntity]:
        return self._run_inference(text)

    def healthcheck(self):  # pragma: no cover
        from care.ocr.base import ProviderHealth
        return ProviderHealth(healthy=True)

    def get_model_manifest(self) -> dict[str, Any]:  # pragma: no cover
        return {}

    def _map_label(self, label: str) -> str | None:
        return "PERSON_NAME" if label.upper() == "PER" else None


def _populated_dir(tmp_path: Path) -> Path:
    d = tmp_path / "model"
    d.mkdir()
    (d / "config.json").write_text("{}", encoding="utf-8")
    (d / "weights.bin").write_bytes(b"\x00\x01\x02")
    return d


# ----- model-dir validation -------------------------------------------------


def test_validate_model_dir_returns_path_when_complete(tmp_path: Path) -> None:
    d = _populated_dir(tmp_path)
    p = _FixtureProvider()
    out = p._validate_model_dir({"model_dir": str(d)}, name="fixture")
    assert out == Path(str(d))


def test_validate_model_dir_rejects_missing_dir(tmp_path: Path) -> None:
    p = _FixtureProvider()
    with pytest.raises(OfflineGuardError, match="not found"):
        p._validate_model_dir(
            {"model_dir": str(tmp_path / "nope")}, name="fixture"
        )


def test_validate_model_dir_rejects_dir_without_required_files(
    tmp_path: Path,
) -> None:
    """The mixin's REQUIRED_MODEL_FILES default is ``("config.json",)``;
    a directory without it fails closed with a clear ``missing`` list."""
    bare = tmp_path / "bare"
    bare.mkdir()
    p = _FixtureProvider()
    with pytest.raises(OfflineGuardError, match=r"missing \['config.json'\]"):
        p._validate_model_dir({"model_dir": str(bare)}, name="fixture")


def test_validate_model_dir_uses_subclass_required_files(tmp_path: Path) -> None:
    """A subclass that overrides ``REQUIRED_MODEL_FILES`` to require
    additional markers must have those checked too."""

    class _Strict(_FixtureProvider):
        REQUIRED_MODEL_FILES = ("config.json", "tokenizer.json")

    d = _populated_dir(tmp_path)  # has config.json but no tokenizer.json
    p = _Strict()
    with pytest.raises(OfflineGuardError, match="tokenizer.json"):
        p._validate_model_dir({"model_dir": str(d)}, name="strict")


# ----- env + config validation ----------------------------------------------


def test_apply_offline_env_sets_every_required_var(monkeypatch) -> None:
    """The mixin re-applies the full HF offline env on every load —
    a previous test or CLI run can't leave the env in a partial state."""
    for key in HF_OFFLINE_ENV:
        monkeypatch.delenv(key, raising=False)
    HFTokenClassificationMixin._apply_offline_env()
    for key, value in HF_OFFLINE_ENV.items():
        assert os.environ[key] == value


def test_validate_aggregation_strategy_accepts_known_strategies() -> None:
    for strategy in _VALID_AGGREGATION_STRATEGIES:
        assert (
            HFTokenClassificationMixin._validate_aggregation_strategy(
                strategy, name="x"
            )
            == strategy
        )


def test_validate_aggregation_strategy_rejects_unknown() -> None:
    with pytest.raises(ConfigError, match="aggregation_strategy"):
        HFTokenClassificationMixin._validate_aggregation_strategy(
            "fancy", name="someplugin"
        )


def test_validate_min_confidence_accepts_in_range() -> None:
    for v in (0.0, 0.5, 1.0):
        assert HFTokenClassificationMixin._validate_min_confidence(v, name="x") == v


@pytest.mark.parametrize("bad", [-0.1, 1.5, 2.0])
def test_validate_min_confidence_rejects_out_of_range(bad: float) -> None:
    with pytest.raises(ConfigError, match="min_confidence"):
        HFTokenClassificationMixin._validate_min_confidence(bad, name="x")


# ----- checksums ------------------------------------------------------------


def test_compute_checksums_records_every_regular_file(tmp_path: Path) -> None:
    d = tmp_path / "ckpt"
    d.mkdir()
    (d / "a").write_bytes(b"hello")
    (d / "sub").mkdir()
    (d / "sub" / "b").write_bytes(b"world")

    out = HFTokenClassificationMixin._compute_checksums(d)

    # Two files, each with a non-empty SHA-256 hex digest.
    assert sorted(out.keys()) == sorted(["a", str(Path("sub") / "b")])
    for digest in out.values():
        assert len(digest) == 64
        int(digest, 16)  # raises if not hex


# ----- inference ------------------------------------------------------------


def test_run_inference_raises_when_not_loaded() -> None:
    p = _FixtureProvider()
    with pytest.raises(RuntimeError, match="load.*must be called first"):
        p._run_inference("anything")


def test_run_inference_returns_empty_for_blank_text() -> None:
    p = _FixtureProvider()
    p._loaded = True
    p._pipeline = _FakePipeline([])
    assert p._run_inference("") == []
    assert p._run_inference("   \n  ") == []


def test_run_inference_absorbs_pipeline_exceptions() -> None:
    """A bad pipeline call must not crash the redaction pipeline —
    return ``[]`` and let upstream code log + continue."""
    class _Boom:
        def __call__(self, text):
            raise RuntimeError("simulated upstream HF crash")

    p = _FixtureProvider()
    p._loaded = True
    p._pipeline = _Boom()
    assert p._run_inference("anything") == []


def test_run_inference_drops_low_confidence_spans() -> None:
    p = _FixtureProvider()
    p._loaded = True
    p._min_confidence = 0.5
    p._pipeline = _FakePipeline(
        [
            {"entity_group": "PER", "score": 0.99, "word": "Smith",
             "start": 0, "end": 5},
            {"entity_group": "PER", "score": 0.30, "word": "Quiet",
             "start": 6, "end": 11},
        ]
    )
    out = p._run_inference("Smith Quiet")
    assert [e.text for e in out] == ["Smith"]


def test_run_inference_drops_unmapped_labels() -> None:
    """``_map_label`` returning None means drop. The fixture provider
    only maps PER, so an ORG span must be skipped."""
    p = _FixtureProvider()
    p._loaded = True
    p._min_confidence = 0.0
    p._pipeline = _FakePipeline(
        [
            {"entity_group": "PER", "score": 0.99, "word": "Smith",
             "start": 0, "end": 5},
            {"entity_group": "ORG", "score": 0.99, "word": "Acme",
             "start": 6, "end": 10},
        ]
    )
    out = p._run_inference("Smith Acme")
    assert [e.entity_type for e in out] == ["PERSON_NAME"]


def test_run_inference_strips_b_i_prefix_from_label() -> None:
    """Some HF checkpoints emit raw ``B-PER`` / ``I-PER`` labels.
    The mixin's ``_extract_label`` strips the prefix so subclasses
    don't have to handle both shapes."""
    p = _FixtureProvider()
    p._loaded = True
    p._min_confidence = 0.0
    p._pipeline = _FakePipeline(
        [{"entity": "B-PER", "score": 0.99, "word": "Smith",
          "start": 0, "end": 5}]
    )
    out = p._run_inference("Smith")
    assert len(out) == 1
    assert out[0].entity_type == "PERSON_NAME"
    # detection_reason carries the *bare* label (after prefix strip).
    assert out[0].detection_reason == "fixture:PER"


def test_run_inference_handles_spans_without_offsets() -> None:
    """If the pipeline emits a span without start/end, the mixin
    still emits the entity (so the redactor can look up by text) but
    leaves the offsets None and flags requires_review=True."""
    p = _FixtureProvider()
    p._loaded = True
    p._min_confidence = 0.0
    p._pipeline = _FakePipeline(
        [{"entity_group": "PER", "score": 0.99, "word": "Smith",
          "start": None, "end": None}]
    )
    out = p._run_inference("Smith")
    assert len(out) == 1
    assert out[0].start_offset is None
    assert out[0].end_offset is None
    assert out[0].requires_review is True
    assert out[0].text == "Smith"


def test_run_inference_records_raw_spans_for_debug() -> None:
    """``_last_raw_spans`` is a debug surface: every raw HF output
    is recorded (sans inference state) so ``--show-raw`` can print
    the unfiltered model output. We never log this."""
    p = _FixtureProvider()
    p._loaded = True
    p._min_confidence = 0.0
    p._pipeline = _FakePipeline(
        [{"entity_group": "PER", "score": 0.99, "word": "Smith",
          "start": 0, "end": 5}]
    )
    p._run_inference("Smith")
    assert len(p._last_raw_spans) == 1
    assert p._last_raw_spans[0]["label"] == "PER"
    assert p._last_raw_spans[0]["score"] == 0.99


def test_run_inference_uses_provider_name_in_detection_reason() -> None:
    """``detection_reason`` is ``{provider_name}:{label}`` so QA
    audits can attribute findings without inspecting the provider
    chain. Hardcoded ``piiranha:`` / ``roberta_ner:`` strings used
    to live in each provider; now they come from ``self.name``."""
    p = _FixtureProvider()
    p._loaded = True
    p._min_confidence = 0.0
    p._pipeline = _FakePipeline(
        [{"entity_group": "PER", "score": 0.9, "word": "X",
          "start": 0, "end": 1}]
    )
    out = p._run_inference("X")
    assert out[0].detection_reason == "fixture:PER"
