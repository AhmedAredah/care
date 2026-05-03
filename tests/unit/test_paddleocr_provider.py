"""PaddleOCR provider skeleton — offline safety guarantees."""
from __future__ import annotations

from pathlib import Path

import pytest

from care.core.errors import ConfigError, OfflineGuardError
from care.ocr.providers.paddleocr_provider import PaddleOCRProvider


def test_paddleocr_disabled_by_default() -> None:
    assert PaddleOCRProvider.enabled_by_default is False


def test_paddleocr_refuses_allow_network() -> None:
    p = PaddleOCRProvider()
    with pytest.raises(ConfigError, match="allow_network"):
        p.load({"allow_network": True})


def test_paddleocr_refuses_local_files_only_false() -> None:
    p = PaddleOCRProvider()
    with pytest.raises(ConfigError, match="local_files_only"):
        p.load({"local_files_only": False})


def test_paddleocr_fails_closed_when_det_dir_missing(tmp_path: Path) -> None:
    p = PaddleOCRProvider()
    with pytest.raises(OfflineGuardError, match="det_model_dir"):
        p.load({
            "det_model_dir": str(tmp_path / "missing_det"),
            "rec_model_dir": str(tmp_path),
        })


def test_paddleocr_fails_closed_when_rec_dir_missing(tmp_path: Path) -> None:
    det = tmp_path / "det"
    det.mkdir()
    p = PaddleOCRProvider()
    with pytest.raises(OfflineGuardError, match="rec_model_dir"):
        p.load({
            "det_model_dir": str(det),
            "rec_model_dir": str(tmp_path / "missing_rec"),
        })


def test_paddleocr_manifest_marks_no_network_no_hallucination() -> None:
    manifest = PaddleOCRProvider().get_model_manifest()
    assert manifest["requires_network"] is False
    assert manifest["enabled_by_default"] is False
    assert manifest["may_hallucinate"] is False
    assert manifest["safe_for_image_redaction"] is True


def test_paddleocr_healthcheck_unhealthy_before_load() -> None:
    p = PaddleOCRProvider()
    h = p.healthcheck()
    assert h.healthy is False
