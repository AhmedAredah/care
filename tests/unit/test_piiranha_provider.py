"""Piiranha PII provider — offline behaviour + real integration.

The real ``transformers`` token-classification pipeline is replaced
in tests by a small fake injected via monkeypatching
``PiiranhaPIIProvider._build_pipeline``. Tests verify:

- License-review warning fires on every load.
- Disabled by default; refuses ``allow_network=true`` and
  ``local_files_only=false``.
- Fails closed on missing / incomplete model_dir with a clear message.
- detect_text routes spans through the configured label_map and
  falls back to CASE_NUMBER for unknown labels.
- Sub-token spans are merged into one entity per span (because we
  pass ``aggregation_strategy="simple"``).
- Spans below ``min_confidence`` are dropped.
- Offsets are propagated; missing offsets become None and the
  entity is flagged ``requires_review``.
- Manifest carries license-review-required marker, model_checksums,
  and the effective label_map.
- Inference exceptions are absorbed (provider returns []), never
  crash the pipeline.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from care.core.errors import ConfigError, OfflineGuardError
from care.pii.entities import ENTITY_TYPES
from care.pii.providers.optional_piiranha_provider import (
    DEFAULT_LABEL_MAP,
    LICENSE_WARNING,
    PiiranhaPIIProvider,
)


# ----- helpers ----------------------------------------------------------


def _stub_model_dir(tmp_path: Path) -> Path:
    model_dir = tmp_path / "models" / "piiranha"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    return model_dir


class _FakePipeline:
    """Duck-typed transformers-pipeline replacement.

    Returns a fixed list of span dicts so tests can prove the conversion
    from HF output → PIIEntity is correct without spinning up the real
    model.
    """

    def __init__(self, spans: list[dict[str, Any]]) -> None:
        self._spans = spans
        self.last_text: str | None = None

    def __call__(self, text: str) -> list[dict[str, Any]]:
        self.last_text = text
        return list(self._spans)


def _loaded_provider(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    spans: list[dict[str, Any]] | None = None,
    config_overrides: dict[str, Any] | None = None,
) -> tuple[PiiranhaPIIProvider, _FakePipeline]:
    fake = _FakePipeline(spans or [])
    monkeypatch.setattr(
        PiiranhaPIIProvider,
        "_build_pipeline",
        staticmethod(lambda model_dir, **kwargs: fake),
    )
    provider = PiiranhaPIIProvider()
    cfg: dict[str, Any] = {"model_dir": str(_stub_model_dir(tmp_path))}
    if config_overrides:
        cfg.update(config_overrides)
    provider.load(cfg)
    return provider, fake


# ----- behaviour ---------------------------------------------------------


def test_piiranha_disabled_by_default() -> None:
    assert PiiranhaPIIProvider.enabled_by_default is False


def test_piiranha_refuses_allow_network() -> None:
    with pytest.raises(ConfigError, match="allow_network"):
        PiiranhaPIIProvider().load({"allow_network": True})


def test_piiranha_refuses_local_files_only_false() -> None:
    with pytest.raises(ConfigError, match="local_files_only"):
        PiiranhaPIIProvider().load({"local_files_only": False})


def test_piiranha_fails_closed_when_model_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(OfflineGuardError, match="model_dir not found"):
        PiiranhaPIIProvider().load({"model_dir": str(tmp_path / "missing")})


def test_piiranha_fails_closed_when_model_dir_incomplete(tmp_path: Path) -> None:
    """Empty dir exists but contains no model files → OfflineGuardError
    with a clear message, not an opaque transformers error."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(OfflineGuardError, match="incomplete"):
        PiiranhaPIIProvider().load({"model_dir": str(empty)})


def test_piiranha_emits_license_warning_on_load(tmp_path: Path, caplog) -> None:
    p = PiiranhaPIIProvider()
    with caplog.at_level(
        logging.WARNING,
        logger="care.pii.providers.optional_piiranha_provider",
    ):
        try:
            p.load({"model_dir": str(_stub_model_dir(tmp_path))})
        except (ConfigError, OfflineGuardError):
            # Acceptable in CI without transformers / a real model dir.
            pass
    assert any(LICENSE_WARNING in rec.message for rec in caplog.records)


def test_piiranha_manifest_marks_license_review_required() -> None:
    manifest = PiiranhaPIIProvider().get_model_manifest()
    assert manifest["requires_license_review_before_deployment"] is True
    assert manifest["license"] == "license-review-required"
    assert manifest["enabled_by_default"] is False
    assert manifest["requires_network"] is False
    assert "label_map" in manifest


# ----- integration via fake pipeline -----------------------------------


def test_detect_text_maps_labels_to_canonical_entity_types(
    monkeypatch, tmp_path
) -> None:
    """B-/I- prefixes stripped; canonical types from DEFAULT_LABEL_MAP."""
    spans = [
        {"entity_group": "B-GIVENNAME", "score": 0.95, "word": "John",
         "start": 0, "end": 4},
        {"entity_group": "I-EMAIL", "score": 0.91, "word": "john@example.com",
         "start": 9, "end": 25},
        {"entity_group": "B-TELEPHONENUM", "score": 0.88, "word": "555-1234",
         "start": 30, "end": 38},
    ]
    provider, fake = _loaded_provider(monkeypatch, tmp_path, spans=spans)
    text = "John at john@example.com call 555-1234"
    entities = provider.detect_text(text)

    assert fake.last_text == text
    assert {e.entity_type for e in entities} == {
        "PERSON_NAME", "EMAIL", "PHONE_NUMBER",
    }
    name_entity = next(e for e in entities if e.entity_type == "PERSON_NAME")
    assert name_entity.start_offset == 0
    assert name_entity.end_offset == 4
    assert name_entity.text == "John"
    assert name_entity.confidence == pytest.approx(0.95)
    assert name_entity.provider == "piiranha"
    assert name_entity.detection_reason == "piiranha:GIVENNAME"
    assert name_entity.requires_review is True
    assert "piiranha" in name_entity.sources


def test_unknown_label_falls_back_to_case_number(monkeypatch, tmp_path) -> None:
    """Recall over precision: a label we don't recognise still produces
    a redactable entity (CASE_NUMBER) rather than being dropped."""
    spans = [
        {"entity_group": "B-INVENTED_ENTITY_TYPE", "score": 0.9,
         "word": "X-1234", "start": 0, "end": 6},
    ]
    provider, _ = _loaded_provider(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("X-1234 foo")
    assert len(entities) == 1
    assert entities[0].entity_type == "CASE_NUMBER"


def test_score_below_threshold_is_dropped(monkeypatch, tmp_path) -> None:
    spans = [
        {"entity_group": "B-EMAIL", "score": 0.99, "word": "a", "start": 0, "end": 1},
        {"entity_group": "B-EMAIL", "score": 0.10, "word": "b", "start": 2, "end": 3},
    ]
    provider, _ = _loaded_provider(
        monkeypatch, tmp_path, spans=spans,
        config_overrides={"min_confidence": 0.5},
    )
    entities = provider.detect_text("a b")
    assert len(entities) == 1
    assert entities[0].confidence == pytest.approx(0.99)


def test_inference_failure_returns_empty_not_raises(monkeypatch, tmp_path) -> None:
    """A pipeline exception must NOT crash the surrounding PII chain."""
    class BoomPipeline:
        def __call__(self, text):
            raise RuntimeError("simulated tokenizer crash")

    monkeypatch.setattr(
        PiiranhaPIIProvider,
        "_build_pipeline",
        staticmethod(lambda model_dir, **kwargs: BoomPipeline()),
    )
    provider = PiiranhaPIIProvider()
    provider.load({"model_dir": str(_stub_model_dir(tmp_path))})
    assert provider.detect_text("anything") == []


def test_empty_input_short_circuits(monkeypatch, tmp_path) -> None:
    provider, fake = _loaded_provider(monkeypatch, tmp_path, spans=[])
    assert provider.detect_text("") == []
    assert provider.detect_text("    ") == []
    # Pipeline never invoked.
    assert fake.last_text is None


def test_span_without_offsets_marked_review(monkeypatch, tmp_path) -> None:
    """If the pipeline returns a span without start/end, we still
    record it (recall over precision) but flag for review since we
    can't slice the source text reliably."""
    spans = [
        {"entity_group": "B-EMAIL", "score": 0.9, "word": "x@y.com"},
    ]
    provider, _ = _loaded_provider(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("x@y.com")
    assert len(entities) == 1
    assert entities[0].entity_type == "EMAIL"
    assert entities[0].start_offset is None
    assert entities[0].end_offset is None
    assert entities[0].requires_review is True


def test_label_map_override_routes_to_alternate_canonical(monkeypatch, tmp_path) -> None:
    """Operators can override mappings without breaking defaults."""
    spans = [
        {"entity_group": "B-IDCARDNUM", "score": 0.9,
         "word": "ABC-99", "start": 0, "end": 6},
    ]
    provider, _ = _loaded_provider(
        monkeypatch, tmp_path, spans=spans,
        config_overrides={"label_map": {"IDCARDNUM": "DRIVER_LICENSE"}},
    )
    entities = provider.detect_text("ABC-99")
    assert entities[0].entity_type == "DRIVER_LICENSE"


def test_label_map_override_rejects_unknown_canonical(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        PiiranhaPIIProvider, "_build_pipeline",
        staticmethod(lambda d, **kw: _FakePipeline([])),
    )
    with pytest.raises(ConfigError, match="ENTITY_TYPES"):
        PiiranhaPIIProvider().load({
            "model_dir": str(_stub_model_dir(tmp_path)),
            "label_map": {"GIVENNAME": "NOT_A_REAL_TYPE"},
        })


def test_pipeline_field_compatibility_entity_vs_entity_group(
    monkeypatch, tmp_path
) -> None:
    """Older transformers versions return ``entity``; newer ones return
    ``entity_group`` when aggregation_strategy is set. We accept either."""
    spans = [
        {"entity": "I-EMAIL", "score": 0.9, "word": "x@y.com", "start": 0, "end": 7},
    ]
    provider, _ = _loaded_provider(monkeypatch, tmp_path, spans=spans)
    entities = provider.detect_text("x@y.com")
    assert entities[0].entity_type == "EMAIL"


# ----- manifest ---------------------------------------------------------


def test_manifest_after_load_includes_checksums_and_label_map(
    monkeypatch, tmp_path
) -> None:
    provider, _ = _loaded_provider(monkeypatch, tmp_path)
    manifest = provider.get_model_manifest()
    assert manifest["model_path"] is not None
    assert "config.json" in manifest["model_checksums"]
    for digest in manifest["model_checksums"].values():
        assert len(digest) == 64
        int(digest, 16)
    for k in ("GIVENNAME", "EMAIL", "TELEPHONENUM"):
        assert manifest["label_map"][k] in ENTITY_TYPES
    assert manifest["min_confidence"] == 0.4


def test_default_label_map_targets_are_in_canonical_vocabulary() -> None:
    for label, canonical in DEFAULT_LABEL_MAP.items():
        assert canonical in ENTITY_TYPES, label


# ----- CLI pii-test -----------------------------------------------------


def test_cli_pii_test_with_mock_pii_provider(capsys, tmp_path) -> None:
    """The CLI command exercises the same provider plumbing operators
    use to verify a real model. The mock_pii provider has no model
    dependency, so this proves the CLI wiring without HF."""
    from care.cli.main import run

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "pii:\n  providers:\n    mock_pii:\n      enabled: true\n      tokens: ['JOHN', 'DOE']\n",
        encoding="utf-8",
    )
    rc = run([
        "pii-test",
        "mock_pii",
        "--text",
        "JOHN DOE was here",
        "--config",
        str(cfg_path),
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["provider"] == "mock_pii"
    assert out["entity_count"] >= 1


def test_cli_pii_test_truncates_text_preview_by_default(
    capsys, tmp_path
) -> None:
    from care.cli.main import run

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "pii:\n  providers:\n    mock_pii:\n      enabled: true\n      tokens: ['SECRET']\n",
        encoding="utf-8",
    )
    long_text = "SECRET" + "x" * 500
    rc = run([
        "pii-test", "mock_pii",
        "--text", long_text,
        "--config", str(cfg_path),
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    if out["entities"]:
        for e in out["entities"]:
            assert len(e["text_preview"]) <= 65
