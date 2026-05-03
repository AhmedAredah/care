"""Presidio PII provider skeleton — offline safety guarantees."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from care.core.constants import HF_OFFLINE_ENV
from care.core.errors import ConfigError, OfflineGuardError
from care.pii.providers.presidio_provider import PresidioPIIProvider


def test_presidio_disabled_by_default() -> None:
    assert PresidioPIIProvider.enabled_by_default is False


def test_presidio_refuses_allow_network() -> None:
    with pytest.raises(ConfigError, match="allow_network"):
        PresidioPIIProvider().load({"allow_network": True})


def test_presidio_refuses_local_files_only_false() -> None:
    with pytest.raises(ConfigError, match="local_files_only"):
        PresidioPIIProvider().load({"local_files_only": False})


def test_presidio_fails_closed_when_model_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(OfflineGuardError, match="model_dir"):
        PresidioPIIProvider().load({"model_dir": str(tmp_path / "missing")})


def test_presidio_sets_hf_offline_env_when_model_dir_exists(tmp_path: Path, monkeypatch) -> None:
    """Even when transformers/presidio is missing, HF env vars get set
    before the import attempt."""
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    for key in HF_OFFLINE_ENV:
        monkeypatch.delenv(key, raising=False)

    p = PresidioPIIProvider()
    with pytest.raises(ConfigError, match="presidio_analyzer"):
        p.load({"model_dir": str(model_dir)})
    for key, expected in HF_OFFLINE_ENV.items():
        assert os.environ.get(key) == expected


def test_presidio_manifest_marks_no_network() -> None:
    manifest = PresidioPIIProvider().get_model_manifest()
    assert manifest["requires_network"] is False
    assert manifest["enabled_by_default"] is False
    assert manifest["safe_for_offline_use"] is True
