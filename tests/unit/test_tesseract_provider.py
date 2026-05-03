"""Tesseract provider skeleton — offline safety guarantees."""
from __future__ import annotations

from pathlib import Path

import pytest

from care.core.errors import ConfigError, OfflineGuardError
from care.ocr.providers.tesseract_provider import TesseractProvider


def test_tesseract_disabled_by_default() -> None:
    assert TesseractProvider.enabled_by_default is False


def test_tesseract_refuses_allow_network() -> None:
    with pytest.raises(ConfigError, match="allow_network"):
        TesseractProvider().load({"allow_network": True})


def test_tesseract_fails_closed_when_tessdata_missing(tmp_path: Path) -> None:
    with pytest.raises(OfflineGuardError, match="tessdata_dir"):
        TesseractProvider().load({"tessdata_dir": str(tmp_path / "missing")})


def test_tesseract_fails_when_binary_not_found(tmp_path: Path, monkeypatch) -> None:
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    monkeypatch.setattr(
        "care.ocr.providers.tesseract_provider.shutil.which",
        lambda *_: None,
    )
    with pytest.raises(ConfigError, match="binary"):
        TesseractProvider().load({"tessdata_dir": str(tessdata)})


def test_tesseract_loads_when_binary_and_tessdata_exist(tmp_path: Path, monkeypatch) -> None:
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    monkeypatch.setattr(
        "care.ocr.providers.tesseract_provider.shutil.which",
        lambda *_: "/usr/bin/tesseract",
    )
    p = TesseractProvider()
    p.load({"tessdata_dir": str(tessdata)})
    assert p.healthcheck().healthy is True


def test_tesseract_manifest_marks_no_network() -> None:
    manifest = TesseractProvider().get_model_manifest()
    assert manifest["requires_network"] is False
    assert manifest["enabled_by_default"] is False
    assert manifest["may_hallucinate"] is False
    assert manifest["safe_for_image_redaction"] is True
