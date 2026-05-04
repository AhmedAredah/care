"""Provider-class helpers in ``care.core.plugin_helpers``.

The module owns two pieces of mechanism every plugin base reuses:

- ``evaluate_model_files_present`` — the boundary-sanitized walk over
  a provider's configured model directories.
- ``assert_offline_config`` — the offline-mode config gate that every
  real plugin's ``load()`` calls as its first line.

Tests below pin both contracts so a future change to the helpers
can't silently shift plugin-wide behaviour.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from care.core.errors import ConfigError
from care.core.plugin_helpers import (
    assert_offline_config,
    evaluate_model_files_present,
)


def test_returns_none_when_no_model_dir_keys_declared() -> None:
    """A pure-Python provider (no model directories) reports None —
    the GUI uses None to mean 'this provider doesn't need a check'."""
    out = evaluate_model_files_present(
        {"some_other_key": "/anything"},
        model_dir_keys=(),
        weight_markers=("config.json",),
    )
    assert out is None


def test_returns_none_when_keys_declared_but_unconfigured() -> None:
    """If keys are declared but the operator hasn't filled any in,
    treat as 'not yet configured' (None) rather than missing (False)."""
    out = evaluate_model_files_present(
        {},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is None


def test_returns_false_for_relative_path(tmp_path: Path) -> None:
    """Relative paths are misconfigurations — normalize_input_path
    rejects them at the boundary, and the helper reports False."""
    out = evaluate_model_files_present(
        {"model_dir": "relative/path"},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is False


def test_returns_false_for_missing_directory(tmp_path: Path) -> None:
    out = evaluate_model_files_present(
        {"model_dir": str(tmp_path / "nope")},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is False


def test_returns_false_for_empty_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    out = evaluate_model_files_present(
        {"model_dir": str(empty)},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is False


def test_returns_true_when_marker_filename_present(tmp_path: Path) -> None:
    populated = tmp_path / "hf"
    populated.mkdir()
    (populated / "config.json").write_text("{}", encoding="utf-8")
    out = evaluate_model_files_present(
        {"model_dir": str(populated)},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is True


def test_returns_true_when_glob_marker_matches(tmp_path: Path) -> None:
    onnx = tmp_path / "onnxtr"
    onnx.mkdir()
    (onnx / "fast_base.onnx").write_bytes(b"\x00")
    out = evaluate_model_files_present(
        {"model_dir": str(onnx)},
        model_dir_keys=("model_dir",),
        weight_markers=("*.onnx",),
    )
    assert out is True


def test_glob_marker_does_not_match_other_format(tmp_path: Path) -> None:
    """A directory full of ``.onnx`` files is NOT a populated HF
    directory — the per-provider WEIGHT_MARKERS prevents this kind of
    cross-format false positive that the old global-glob approach was
    blind to."""
    onnx = tmp_path / "wrongdir"
    onnx.mkdir()
    (onnx / "fast_base.onnx").write_bytes(b"\x00")
    out = evaluate_model_files_present(
        {"model_dir": str(onnx)},
        model_dir_keys=("model_dir",),
        weight_markers=("config.json",),
    )
    assert out is False


def test_multi_dir_provider_requires_every_configured_dir(tmp_path: Path) -> None:
    """PaddleOCR-style: ``det_model_dir`` populated, ``rec_model_dir``
    empty — overall result is False."""
    det = tmp_path / "det"
    rec = tmp_path / "rec"
    det.mkdir()
    rec.mkdir()
    (det / "inference.pdmodel").write_bytes(b"\x00")
    out = evaluate_model_files_present(
        {"det_model_dir": str(det), "rec_model_dir": str(rec)},
        model_dir_keys=("det_model_dir", "rec_model_dir", "cls_model_dir"),
        weight_markers=("*.pdmodel", "*.pdiparams"),
    )
    assert out is False


def test_multi_dir_provider_skips_unset_keys(tmp_path: Path) -> None:
    """``cls_model_dir`` is unset — the helper checks only the dirs the
    operator filled in, matching the existing PaddleOCR config shape."""
    det = tmp_path / "det"
    rec = tmp_path / "rec"
    det.mkdir()
    rec.mkdir()
    (det / "inference.pdmodel").write_bytes(b"\x00")
    (rec / "inference.pdmodel").write_bytes(b"\x00")
    out = evaluate_model_files_present(
        {"det_model_dir": str(det), "rec_model_dir": str(rec)},
        model_dir_keys=("det_model_dir", "rec_model_dir", "cls_model_dir"),
        weight_markers=("*.pdmodel", "*.pdiparams"),
    )
    assert out is True


def test_empty_weight_markers_means_any_directory_counts(tmp_path: Path) -> None:
    """A provider that just needs the directory to exist (no specific
    marker file) declares an empty WEIGHT_MARKERS tuple."""
    any_dir = tmp_path / "anything"
    any_dir.mkdir()
    out = evaluate_model_files_present(
        {"model_dir": str(any_dir)},
        model_dir_keys=("model_dir",),
        weight_markers=(),
    )
    assert out is True


# ---- assert_offline_config -------------------------------------------------


def test_assert_offline_config_accepts_default_offline_config() -> None:
    """The default config has neither ``allow_network`` nor
    ``local_files_only`` set — the helper must accept that and assume
    offline-only mode (the safe default)."""
    assert_offline_config("anyplugin", {})  # must not raise


def test_assert_offline_config_accepts_explicit_offline_values() -> None:
    """``allow_network=false`` + ``local_files_only=true`` is the
    legitimate explicit-offline config; must pass."""
    assert_offline_config(
        "anyplugin",
        {"allow_network": False, "local_files_only": True},
    )


def test_assert_offline_config_rejects_allow_network_true() -> None:
    with pytest.raises(ConfigError, match="someplugin.allow_network"):
        assert_offline_config("someplugin", {"allow_network": True})


def test_assert_offline_config_rejects_local_files_only_false() -> None:
    with pytest.raises(ConfigError, match="someplugin.local_files_only"):
        assert_offline_config("someplugin", {"local_files_only": False})


def test_assert_offline_config_error_message_includes_provider_name() -> None:
    """When several providers are stacked in a chain, an offline
    misconfiguration must surface WHICH provider tripped — that's the
    only thing the operator can act on."""
    with pytest.raises(ConfigError) as exc:
        assert_offline_config("piiranha", {"allow_network": True})
    assert "piiranha" in str(exc.value)


def test_assert_offline_config_checks_allow_network_first() -> None:
    """If both flags are wrong, the network flag is the more dangerous
    one — surface it first so the operator's first remediation
    addresses the root cause."""
    with pytest.raises(ConfigError, match="allow_network"):
        assert_offline_config(
            "anyplugin",
            {"allow_network": True, "local_files_only": False},
        )
