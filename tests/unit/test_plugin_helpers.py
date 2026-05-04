"""Provider-class helper for ``model_files_present``.

The helper owns the boundary-sanitized walk over a provider's
configured model directories. The endpoint just calls
``cls.model_files_present(provider_cfg)`` — every plugin-format-aware
piece of logic lives in this helper plus each provider class's
``MODEL_DIR_KEYS`` / ``WEIGHT_MARKERS`` declarations.
"""
from __future__ import annotations

from pathlib import Path

from care.core.plugin_helpers import evaluate_model_files_present


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
