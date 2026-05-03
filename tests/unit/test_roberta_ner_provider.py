"""RoBERTa NER PII provider — offline behaviour + integration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from care.core.errors import ConfigError, OfflineGuardError
from care.pii.entities import ENTITY_TYPES
from care.pii.providers.roberta_ner_provider import (
    DEFAULT_LABEL_MAP,
    RobertaNERProvider,
)
from care.pii.registry import get_registry, reset_registry


def _stub_model_dir(tmp_path: Path) -> Path:
    model_dir = tmp_path / "models" / "roberta_ner"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    return model_dir


class _FakePipeline:
    def __init__(self, spans: list[dict[str, Any]]) -> None:
        self._spans = spans
        self.last_text: str | None = None

    def __call__(self, text: str) -> list[dict[str, Any]]:
        self.last_text = text
        return list(self._spans)


def _loaded(
    monkeypatch, tmp_path, *, spans=None, config_overrides=None
) -> tuple[RobertaNERProvider, _FakePipeline]:
    fake = _FakePipeline(spans or [])
    monkeypatch.setattr(
        RobertaNERProvider,
        "_build_pipeline",
        staticmethod(lambda model_dir, **kwargs: fake),
    )
    provider = RobertaNERProvider()
    cfg: dict[str, Any] = {"model_dir": str(_stub_model_dir(tmp_path))}
    if config_overrides:
        cfg.update(config_overrides)
    provider.load(cfg)
    return provider, fake


# ----- behaviour ---------------------------------------------------------


def test_disabled_by_default() -> None:
    assert RobertaNERProvider.enabled_by_default is False


def test_registered_in_pii_registry() -> None:
    reset_registry()
    try:
        registry = get_registry()
        assert registry.has("roberta_ner")
        assert registry.get("roberta_ner") is RobertaNERProvider
    finally:
        reset_registry()


def test_refuses_allow_network() -> None:
    with pytest.raises(ConfigError, match="allow_network"):
        RobertaNERProvider().load({"allow_network": True})


def test_refuses_local_files_only_false() -> None:
    with pytest.raises(ConfigError, match="local_files_only"):
        RobertaNERProvider().load({"local_files_only": False})


def test_fails_closed_when_model_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(OfflineGuardError, match="model_dir not found"):
        RobertaNERProvider().load(
            {"model_dir": str(tmp_path / "missing")}
        )


def test_fails_closed_when_model_dir_incomplete(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(OfflineGuardError, match="incomplete"):
        RobertaNERProvider().load({"model_dir": str(empty)})


def test_manifest_marks_mit_license() -> None:
    """RoBERTa-large-ner-english is MIT — no review-required flag."""
    manifest = RobertaNERProvider().get_model_manifest()
    assert manifest["license"] == "MIT"
    assert manifest["enabled_by_default"] is False
    assert manifest["requires_network"] is False
    assert "label_map" in manifest


# ----- integration via fake pipeline -----------------------------------


def test_per_label_maps_to_person_name(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "PER", "score": 0.99, "word": "John Doe",
         "start": 7, "end": 15},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("Driver John Doe lives here")
    assert len(entities) == 1
    assert entities[0].entity_type == "PERSON_NAME"
    assert entities[0].text == "John Doe"
    assert entities[0].provider == "roberta_ner"
    assert entities[0].detection_reason == "roberta_ner:PER"
    assert entities[0].requires_review is True


def test_loc_label_maps_to_address(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "LOC", "score": 0.95, "word": "Springfield",
         "start": 0, "end": 11},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("Springfield, IL")
    assert len(entities) == 1
    assert entities[0].entity_type == "ADDRESS"


def test_org_dropped_by_default(monkeypatch, tmp_path) -> None:
    """Default: ORG is not PII in a crash-report context. Operators
    that want to redact organisations must opt in via label_map."""
    spans = [
        {"entity_group": "ORG", "score": 0.99, "word": "Acme Insurance",
         "start": 0, "end": 14},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("Acme Insurance pays")
    assert entities == []


def test_misc_dropped_by_default(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "MISC", "score": 0.99, "word": "Toyota",
         "start": 0, "end": 6},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("Toyota Camry")
    assert entities == []


def test_org_can_be_opted_into_via_label_map(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "ORG", "score": 0.99, "word": "Acme",
         "start": 0, "end": 4},
    ]
    provider, _ = _loaded(
        monkeypatch, tmp_path, spans=spans,
        config_overrides={"label_map": {"ORG": "VEHICLE_OWNER_INFO"}},
    )
    entities = provider.detect_text("Acme")
    assert len(entities) == 1
    assert entities[0].entity_type == "VEHICLE_OWNER_INFO"


def test_label_map_explicit_none_drops(monkeypatch, tmp_path) -> None:
    """Operator can explicitly drop a label via ``None``."""
    spans = [
        {"entity_group": "PER", "score": 0.99, "word": "John",
         "start": 0, "end": 4},
    ]
    provider, _ = _loaded(
        monkeypatch, tmp_path, spans=spans,
        config_overrides={"label_map": {"PER": None}},
    )
    assert provider.detect_text("John") == []


def test_label_map_rejects_unknown_canonical(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        RobertaNERProvider, "_build_pipeline",
        staticmethod(lambda d, **kw: _FakePipeline([])),
    )
    with pytest.raises(ConfigError, match="ENTITY_TYPES"):
        RobertaNERProvider().load({
            "model_dir": str(_stub_model_dir(tmp_path)),
            "label_map": {"PER": "NOT_A_REAL_TYPE"},
        })


def test_score_below_threshold_dropped(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "PER", "score": 0.99, "word": "Alice",
         "start": 0, "end": 5},
        {"entity_group": "PER", "score": 0.50, "word": "Bob",
         "start": 6, "end": 9},
    ]
    provider, _ = _loaded(
        monkeypatch, tmp_path, spans=spans,
        config_overrides={"min_confidence": 0.9},
    )
    entities = provider.detect_text("Alice Bob")
    assert len(entities) == 1
    assert entities[0].text == "Alice"


def test_inference_failure_returns_empty(monkeypatch, tmp_path) -> None:
    class BoomPipeline:
        def __call__(self, text):
            raise RuntimeError("simulated tokenizer crash")

    monkeypatch.setattr(
        RobertaNERProvider, "_build_pipeline",
        staticmethod(lambda d, **kw: BoomPipeline()),
    )
    p = RobertaNERProvider()
    p.load({"model_dir": str(_stub_model_dir(tmp_path))})
    assert p.detect_text("anything") == []


def test_empty_input_short_circuits(monkeypatch, tmp_path) -> None:
    provider, fake = _loaded(monkeypatch, tmp_path, spans=[])
    assert provider.detect_text("") == []
    assert provider.detect_text("    ") == []
    assert fake.last_text is None


def test_b_i_prefix_stripped(monkeypatch, tmp_path) -> None:
    """The default checkpoint emits bare labels but operators may
    point us at a CoNLL checkpoint that retained ``B-`` / ``I-``."""
    spans = [
        {"entity": "B-PER", "score": 0.99, "word": "Alice", "start": 0, "end": 5},
        {"entity": "I-PER", "score": 0.99, "word": "Smith", "start": 6, "end": 11},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("Alice Smith")
    assert len(entities) == 2
    assert all(e.entity_type == "PERSON_NAME" for e in entities)


def test_aggregation_strategy_passed_through(monkeypatch, tmp_path) -> None:
    seen: dict[str, Any] = {}

    def fake_build(model_dir: Path, *, aggregation_strategy: str = "simple"):
        seen["agg"] = aggregation_strategy
        return _FakePipeline([])

    monkeypatch.setattr(
        RobertaNERProvider, "_build_pipeline", staticmethod(fake_build)
    )
    p = RobertaNERProvider()
    p.load({
        "model_dir": str(_stub_model_dir(tmp_path)),
        "aggregation_strategy": "max",
    })
    assert seen["agg"] == "max"


def test_default_label_map_targets_in_canonical_vocabulary() -> None:
    for label, canonical in DEFAULT_LABEL_MAP.items():
        if canonical is None:
            continue
        assert canonical in ENTITY_TYPES, label


def test_manifest_after_load_includes_checksums(monkeypatch, tmp_path) -> None:
    provider, _ = _loaded(monkeypatch, tmp_path)
    manifest = provider.get_model_manifest()
    assert manifest["model_path"] is not None
    assert "config.json" in manifest["model_checksums"]
    for digest in manifest["model_checksums"].values():
        assert len(digest) == 64
        int(digest, 16)
    assert manifest["min_confidence"] == 0.85
    assert manifest["aggregation_strategy"] == "simple"
