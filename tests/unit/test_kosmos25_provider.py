"""Kosmos-2.5 VLM provider skeleton — offline behaviour + manifest checksums."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from care.core.constants import HF_OFFLINE_ENV
from care.core.errors import ConfigError, OfflineGuardError
from care.document_ai.providers.kosmos25_provider import Kosmos25Provider


def test_kosmos25_disabled_by_default() -> None:
    """test_kosmos25_provider_disabled_by_default."""
    assert Kosmos25Provider.enabled_by_default is False


def test_kosmos25_refuses_allow_network() -> None:
    """test_kosmos25_provider_uses_local_model_path_only — `allow_network`
    must always be false."""
    with pytest.raises(ConfigError, match="allow_network"):
        Kosmos25Provider().load({"allow_network": True})


def test_kosmos25_refuses_local_files_only_false() -> None:
    """test_kosmos25_provider_uses_local_files_only."""
    with pytest.raises(ConfigError, match="local_files_only"):
        Kosmos25Provider().load({"local_files_only": False})


def test_kosmos25_fails_closed_when_model_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(OfflineGuardError, match="model_dir"):
        Kosmos25Provider().load({"model_dir": str(tmp_path / "missing")})


def test_kosmos25_sets_hf_offline_env_vars(tmp_path: Path, monkeypatch) -> None:
    """test_offline_mode_blocks_huggingface_downloads — env vars must be set
    by the loader before any HF import attempt."""
    model_dir = tmp_path / "kosmos"
    model_dir.mkdir()
    for key in HF_OFFLINE_ENV:
        monkeypatch.delenv(key, raising=False)

    p = Kosmos25Provider()
    # transformers may or may not be installed; either way the env vars
    # must already be set by the time the import is attempted.
    try:
        p.load({"model_dir": str(model_dir), "processor_dir": str(model_dir)})
    except ConfigError:
        pass

    for key, expected in HF_OFFLINE_ENV.items():
        assert os.environ.get(key) == expected


def test_kosmos25_manifest_includes_model_checksums(tmp_path: Path, monkeypatch) -> None:
    """test_document_ai_manifest_includes_model_checksums."""
    model_dir = tmp_path / "kosmos"
    model_dir.mkdir()
    fake_weight = model_dir / "model.safetensors"
    fake_weight.write_bytes(b"weight-bytes")

    monkeypatch.setattr(
        "care.document_ai.providers.kosmos25_provider.Kosmos25Provider._compute_checksums",
        staticmethod(
            lambda model_dir: {
                "model.safetensors": hashlib.sha256(b"weight-bytes").hexdigest()
            }
        ),
    )
    p = Kosmos25Provider()
    try:
        p.load({"model_dir": str(model_dir), "processor_dir": str(model_dir)})
    except ConfigError:
        pass  # transformers not installed in CI — that's fine.

    manifest = p.get_model_manifest()
    assert manifest["model_checksums"] == {
        "model.safetensors": hashlib.sha256(b"weight-bytes").hexdigest(),
    }
    assert manifest["model_path"] == str(model_dir)
    assert manifest["local_files_only"] is True
    assert manifest["safe_for_image_redaction"] is False
    assert manifest["may_hallucinate"] is True
    assert manifest["requires_network"] is False
    assert manifest["enabled_by_default"] is False
    # HF env vars are recorded in the manifest.
    assert manifest["hf_offline_env"]["HF_HUB_OFFLINE"] == "1"
    assert manifest["hf_offline_env"]["TRANSFORMERS_OFFLINE"] == "1"


def test_kosmos25_compute_checksums_walks_dir(tmp_path: Path) -> None:
    (tmp_path / "a.bin").write_bytes(b"alpha")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.bin").write_bytes(b"beta")
    sums = Kosmos25Provider._compute_checksums(tmp_path)
    expected_a = hashlib.sha256(b"alpha").hexdigest()
    expected_b = hashlib.sha256(b"beta").hexdigest()
    assert sums == {"a.bin": expected_a, "sub/b.bin": expected_b} or \
           sums == {"a.bin": expected_a, "sub\\b.bin": expected_b}
