"""OnnxTR provider — offline safety guarantees.

The runtime ``onnxtr`` library is *not* a hard dependency. These tests
exercise the load-time guards that fire before any ``import onnxtr``,
plus the healthcheck and manifest shape — all of which must work in a
core-only environment.

Anything that requires real ONNX weights or the runtime predictor is
deferred to packaging tests run against a populated model directory.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from care.core.errors import ConfigError, OfflineGuardError
from care.ocr.providers.onnxtr_provider import OnnxTROCRProvider
from care.ocr.registry import get_registry, reset_registry


@pytest.fixture(autouse=True)
def _registry_reset():
    reset_registry()
    yield
    reset_registry()


def test_onnxtr_disabled_by_default() -> None:
    assert OnnxTROCRProvider.enabled_by_default is False
    assert OnnxTROCRProvider.requires_network is False


def test_onnxtr_registered_under_canonical_name() -> None:
    cls = get_registry().get("onnxtr")
    assert cls is OnnxTROCRProvider


def test_onnxtr_refuses_allow_network() -> None:
    p = OnnxTROCRProvider()
    with pytest.raises(ConfigError, match="allow_network"):
        p.load({"allow_network": True})


def test_onnxtr_refuses_local_files_only_false() -> None:
    p = OnnxTROCRProvider()
    with pytest.raises(ConfigError, match="local_files_only"):
        p.load({"local_files_only": False})


def test_onnxtr_rejects_unknown_det_arch(tmp_path: Path) -> None:
    p = OnnxTROCRProvider()
    with pytest.raises(ConfigError, match="det_arch"):
        p.load({
            "model_dir": str(tmp_path),
            "det_arch": "not_a_real_detector",
        })


def test_onnxtr_rejects_unknown_reco_arch(tmp_path: Path) -> None:
    p = OnnxTROCRProvider()
    with pytest.raises(ConfigError, match="reco_arch"):
        p.load({
            "model_dir": str(tmp_path),
            "reco_arch": "not_a_real_recognizer",
        })


def test_onnxtr_fails_closed_when_model_dir_missing(tmp_path: Path) -> None:
    p = OnnxTROCRProvider()
    with pytest.raises(OfflineGuardError, match="model_dir"):
        p.load({"model_dir": str(tmp_path / "absent")})


def test_onnxtr_fails_closed_when_model_dir_empty(tmp_path: Path) -> None:
    p = OnnxTROCRProvider()
    # model_dir exists but the expected weight files don't.
    with pytest.raises(OfflineGuardError, match="det_file"):
        p.load({"model_dir": str(tmp_path)})


def test_onnxtr_fails_closed_when_only_det_present(tmp_path: Path) -> None:
    (tmp_path / "fast_base.onnx").write_bytes(b"\x00")
    p = OnnxTROCRProvider()
    with pytest.raises(OfflineGuardError, match="reco_file"):
        p.load({"model_dir": str(tmp_path)})


def test_onnxtr_rejects_bad_threshold(tmp_path: Path) -> None:
    (tmp_path / "fast_base.onnx").write_bytes(b"\x00")
    (tmp_path / "crnn_vgg16_bn.onnx").write_bytes(b"\x00")
    p = OnnxTROCRProvider()
    with pytest.raises(ConfigError, match="low_confidence_threshold"):
        p.load({
            "model_dir": str(tmp_path),
            "low_confidence_threshold": 1.5,
        })


def test_onnxtr_rejects_path_traversal(tmp_path: Path) -> None:
    """Traversal-y filenames must be rejected even before the file
    existence check, so a misconfigured config can't read outside
    model_dir."""
    p = OnnxTROCRProvider()
    with pytest.raises(ConfigError, match="resolves outside model_dir"):
        p.load({
            "model_dir": str(tmp_path),
            "det_file": "../../../etc/passwd",
        })


def test_onnxtr_healthcheck_unhealthy_before_load() -> None:
    h = OnnxTROCRProvider().healthcheck()
    assert h.healthy is False
    assert "not loaded" in h.detail


def test_onnxtr_manifest_marks_no_network_no_hallucination_pre_load() -> None:
    """An unloaded provider returns an empty manifest dict — operators
    can still inspect class-level fields via the registry walk."""
    manifest = OnnxTROCRProvider().get_model_manifest()
    assert manifest == {}


def test_onnxtr_supports_flags_at_class_level() -> None:
    assert OnnxTROCRProvider.supports_word_bboxes is True
    assert OnnxTROCRProvider.supports_line_bboxes is True
    assert OnnxTROCRProvider.supports_confidence is True
