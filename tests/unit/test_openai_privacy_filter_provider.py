"""OpenAI Privacy Filter PII provider — offline behaviour + integration."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from care.core.errors import ConfigError, OfflineGuardError
from care.pii.entities import ENTITY_TYPES
from care.pii.providers.openai_privacy_filter_provider import (
    DEFAULT_LABEL_MAP,
    OpenAIPrivacyFilterProvider,
)
from care.pii.registry import get_registry, reset_registry


def _stub_model_dir(tmp_path: Path) -> Path:
    model_dir = tmp_path / "models" / "openai_privacy_filter"
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
) -> tuple[OpenAIPrivacyFilterProvider, _FakePipeline]:
    fake = _FakePipeline(spans or [])
    monkeypatch.setattr(
        OpenAIPrivacyFilterProvider,
        "_build_pipeline",
        staticmethod(lambda model_dir, **kwargs: fake),
    )
    provider = OpenAIPrivacyFilterProvider()
    cfg: dict[str, Any] = {"model_dir": str(_stub_model_dir(tmp_path))}
    if config_overrides:
        cfg.update(config_overrides)
    provider.load(cfg)
    return provider, fake


# ----- behaviour ---------------------------------------------------------


def test_disabled_by_default() -> None:
    assert OpenAIPrivacyFilterProvider.enabled_by_default is False


def test_registered_in_pii_registry() -> None:
    reset_registry()
    try:
        registry = get_registry()
        assert registry.has("openai_privacy_filter")
        assert (
            registry.get("openai_privacy_filter") is OpenAIPrivacyFilterProvider
        )
    finally:
        reset_registry()


def test_refuses_allow_network() -> None:
    with pytest.raises(ConfigError, match="allow_network"):
        OpenAIPrivacyFilterProvider().load({"allow_network": True})


def test_refuses_local_files_only_false() -> None:
    with pytest.raises(ConfigError, match="local_files_only"):
        OpenAIPrivacyFilterProvider().load({"local_files_only": False})


def test_fails_closed_when_model_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(OfflineGuardError, match="model_dir not found"):
        OpenAIPrivacyFilterProvider().load(
            {"model_dir": str(tmp_path / "missing")}
        )


def test_fails_closed_when_model_dir_incomplete(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(OfflineGuardError, match="incomplete"):
        OpenAIPrivacyFilterProvider().load({"model_dir": str(empty)})


def test_manifest_marks_apache_license() -> None:
    """Privacy-filter is Apache-2.0 — no review-required flag."""
    manifest = OpenAIPrivacyFilterProvider().get_model_manifest()
    assert manifest["license"] == "Apache-2.0"
    assert manifest["enabled_by_default"] is False
    assert manifest["requires_network"] is False
    assert "label_map" in manifest


# ----- integration via fake pipeline -----------------------------------


def test_private_person_maps_to_person_name(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "private_person", "score": 0.999, "word": "Harry Potter",
         "start": 11, "end": 23},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("My name is Harry Potter")
    assert len(entities) == 1
    assert entities[0].entity_type == "PERSON_NAME"
    assert entities[0].text == "Harry Potter"
    assert entities[0].provider == "openai_privacy_filter"
    assert entities[0].detection_reason == "openai_privacy_filter:private_person"
    assert entities[0].requires_review is True


def test_private_email_maps_to_email(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "private_email", "score": 0.999,
         "word": "harry.potter@hogwarts.edu", "start": 0, "end": 25},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("harry.potter@hogwarts.edu wrote")
    assert len(entities) == 1
    assert entities[0].entity_type == "EMAIL"


def test_private_address_maps_to_address(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "private_address", "score": 0.99,
         "word": "221B Baker Street", "start": 0, "end": 17},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("221B Baker Street, London")
    assert entities[0].entity_type == "ADDRESS"


def test_private_phone_maps_to_phone_number(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "private_phone", "score": 0.99,
         "word": "555-123-4567", "start": 0, "end": 12},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("555-123-4567")
    assert entities[0].entity_type == "PHONE_NUMBER"


def test_private_date_maps_to_dob(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "private_date", "score": 0.97,
         "word": "1990-01-01", "start": 0, "end": 10},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("1990-01-01")
    assert entities[0].entity_type == "DATE_OF_BIRTH"


def test_account_number_maps_to_insurance_policy(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "account_number", "score": 0.96,
         "word": "POL-12345-678", "start": 0, "end": 13},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("POL-12345-678")
    assert entities[0].entity_type == "INSURANCE_POLICY"


def test_secret_maps_to_case_number(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "secret", "score": 0.95,
         "word": "sk-live-abc123", "start": 0, "end": 14},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("sk-live-abc123")
    assert entities[0].entity_type == "CASE_NUMBER"


def test_private_url_dropped_by_default(monkeypatch, tmp_path) -> None:
    """Default policy: URLs are typically external refs in crash
    reports, not PII. Operators must opt in via label_map."""
    spans = [
        {"entity_group": "private_url", "score": 0.99,
         "word": "https://example.com/case/123", "start": 0, "end": 28},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("see https://example.com/case/123")
    assert entities == []


def test_private_url_can_be_opted_into_via_label_map(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "private_url", "score": 0.99,
         "word": "https://example.com", "start": 0, "end": 19},
    ]
    provider, _ = _loaded(
        monkeypatch, tmp_path, spans=spans,
        config_overrides={"label_map": {"private_url": "CASE_NUMBER"}},
    )
    entities = provider.detect_text("https://example.com")
    assert len(entities) == 1
    assert entities[0].entity_type == "CASE_NUMBER"


def test_label_map_explicit_none_drops(monkeypatch, tmp_path) -> None:
    """Operator can explicitly drop a label via ``None``."""
    spans = [
        {"entity_group": "private_person", "score": 0.99, "word": "Alice",
         "start": 0, "end": 5},
    ]
    provider, _ = _loaded(
        monkeypatch, tmp_path, spans=spans,
        config_overrides={"label_map": {"private_person": None}},
    )
    assert provider.detect_text("Alice") == []


def test_label_map_rejects_unknown_canonical(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        OpenAIPrivacyFilterProvider, "_build_pipeline",
        staticmethod(lambda d, **kw: _FakePipeline([])),
    )
    with pytest.raises(ConfigError, match="ENTITY_TYPES"):
        OpenAIPrivacyFilterProvider().load({
            "model_dir": str(_stub_model_dir(tmp_path)),
            "label_map": {"private_person": "NOT_A_REAL_TYPE"},
        })


def test_label_map_rejects_non_dict() -> None:
    with pytest.raises(ConfigError, match="must be a dict"):
        OpenAIPrivacyFilterProvider._merge_label_map(["not", "a", "dict"])


def test_score_below_threshold_dropped(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "private_person", "score": 0.99, "word": "Alice",
         "start": 0, "end": 5},
        {"entity_group": "private_person", "score": 0.50, "word": "Bob",
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
        OpenAIPrivacyFilterProvider, "_build_pipeline",
        staticmethod(lambda d, **kw: BoomPipeline()),
    )
    p = OpenAIPrivacyFilterProvider()
    p.load({"model_dir": str(_stub_model_dir(tmp_path))})
    assert p.detect_text("anything") == []


def test_empty_input_short_circuits(monkeypatch, tmp_path) -> None:
    provider, fake = _loaded(monkeypatch, tmp_path, spans=[])
    assert provider.detect_text("") == []
    assert provider.detect_text("    ") == []
    assert fake.last_text is None


def test_bioes_prefix_stripped(monkeypatch, tmp_path) -> None:
    """Privacy-filter trains on BIOES tagging (B-/I-/E-/S-). Standard
    ``aggregation_strategy="simple"`` collapses spans and returns bare
    labels, but the mixin strips defensively if a prefix slips through.
    """
    spans = [
        {"entity": "B-private_person", "score": 0.99, "word": "Alice",
         "start": 0, "end": 5},
        {"entity": "E-private_person", "score": 0.99, "word": "Smith",
         "start": 6, "end": 11},
        {"entity": "S-private_email", "score": 0.99,
         "word": "alice@example.com", "start": 12, "end": 29},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("Alice Smith alice@example.com")
    assert len(entities) == 3
    assert entities[0].entity_type == "PERSON_NAME"
    assert entities[1].entity_type == "PERSON_NAME"
    assert entities[2].entity_type == "EMAIL"


def test_aggregation_strategy_passed_through(monkeypatch, tmp_path) -> None:
    seen: dict[str, Any] = {}

    def fake_build(model_dir: Path, *, aggregation_strategy: str = "simple"):
        seen["agg"] = aggregation_strategy
        return _FakePipeline([])

    monkeypatch.setattr(
        OpenAIPrivacyFilterProvider, "_build_pipeline", staticmethod(fake_build)
    )
    p = OpenAIPrivacyFilterProvider()
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


def test_unknown_label_dropped(monkeypatch, tmp_path) -> None:
    """A label outside the eight known privacy-filter labels (e.g.
    from a custom fine-tune) is dropped — predictable over silent
    fallback. Operators that want a fallback can wire it via
    ``label_map``."""
    spans = [
        {"entity_group": "custom_label", "score": 0.99,
         "word": "something", "start": 0, "end": 9},
    ]
    provider, _ = _loaded(monkeypatch, tmp_path, spans=spans)
    assert provider.detect_text("something") == []


def test_supported_entities_excludes_dropped_labels() -> None:
    """``private_url`` defaults to None — so the manifest's
    supported_entities list should not advertise an entity for it."""
    cls_supported = OpenAIPrivacyFilterProvider.supported_entities
    assert "PERSON_NAME" in cls_supported
    assert "EMAIL" in cls_supported
    # private_url -> None, so we don't claim a canonical entity for it
    assert all(e in ENTITY_TYPES for e in cls_supported)


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


def test_label_keys_normalised_to_lowercase(monkeypatch, tmp_path) -> None:
    """Operator-supplied keys are normalised to lowercase to match
    the model's output convention."""
    spans = [
        {"entity_group": "private_person", "score": 0.99, "word": "Alice",
         "start": 0, "end": 5},
    ]
    provider, _ = _loaded(
        monkeypatch, tmp_path, spans=spans,
        config_overrides={"label_map": {"PRIVATE_PERSON": "WITNESS_INFO"}},
    )
    entities = provider.detect_text("Alice")
    assert entities[0].entity_type == "WITNESS_INFO"
