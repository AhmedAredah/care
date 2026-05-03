"""End-to-end plugin enable/disable flow (Phase 13.4).

The Plugins page builds a tiny patch of shape::

    {"<section>": {"provider_chain": [...], "providers": {<name>: {"enabled": <bool>}}}}

and runs it through ``POST /api/config/validate`` followed by
``PATCH /api/config``. These tests exercise that round trip end to
end so a regression in either endpoint surfaces immediately.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml as pyyaml

from care.api.routes_config import patch_config, validate_config
from care.core.config import AppConfig, PIISection


def _redirect_writer(monkeypatch, tmp_path: Path, initial: str) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(initial, encoding="utf-8")
    from care.core import config_writer

    monkeypatch.setattr(config_writer, "resolve_write_path", lambda *a, **kw: cfg)
    return cfg


def _build_enable_patch(section: str, name: str, current_chain: list[str]) -> dict:
    next_chain = list(current_chain)
    if name not in next_chain:
        next_chain.append(name)
    return {
        section: {
            "provider_chain": next_chain,
            "providers": {name: {"enabled": True}},
        }
    }


def _build_disable_patch(section: str, name: str, current_chain: list[str]) -> dict:
    next_chain = [n for n in current_chain if n != name]
    return {
        section: {
            "provider_chain": next_chain,
            "providers": {name: {"enabled": False}},
        }
    }


def test_enable_pii_provider_writes_chain_and_enabled_flag(
    monkeypatch, tmp_path: Path
) -> None:
    cfg_path = _redirect_writer(
        monkeypatch,
        tmp_path,
        "pii:\n"
        "  provider_chain:\n"
        "    - regex\n"
        "  providers:\n"
        "    regex:\n"
        "      enabled: true\n"
        "    roberta_ner:\n"
        "      enabled: false\n",
    )
    current = AppConfig(
        pii=PIISection(
            provider_chain=["regex"],
            providers={
                "regex": {"enabled": True},
                "roberta_ner": {"enabled": False},
            },
        )
    )
    patch = _build_enable_patch("pii", "roberta_ner", ["regex"])

    pre = validate_config(body=patch, current=current)
    assert pre["ok"] is True

    response = patch_config(body=patch, current=current)
    assert response["ok"] is True

    on_disk = pyyaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert on_disk["pii"]["provider_chain"] == ["regex", "roberta_ner"]
    assert on_disk["pii"]["providers"]["roberta_ner"]["enabled"] is True
    # regex left alone.
    assert on_disk["pii"]["providers"]["regex"]["enabled"] is True


def test_disable_pii_provider_removes_chain_and_clears_flag(
    monkeypatch, tmp_path: Path
) -> None:
    cfg_path = _redirect_writer(
        monkeypatch,
        tmp_path,
        "pii:\n"
        "  provider_chain:\n"
        "    - regex\n"
        "    - roberta_ner\n"
        "  providers:\n"
        "    regex:\n"
        "      enabled: true\n"
        "    roberta_ner:\n"
        "      enabled: true\n",
    )
    current = AppConfig(
        pii=PIISection(
            provider_chain=["regex", "roberta_ner"],
            providers={
                "regex": {"enabled": True},
                "roberta_ner": {"enabled": True},
            },
        )
    )
    patch = _build_disable_patch("pii", "roberta_ner", ["regex", "roberta_ner"])
    response = patch_config(body=patch, current=current)
    assert response["ok"] is True

    on_disk = pyyaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert on_disk["pii"]["provider_chain"] == ["regex"]
    assert on_disk["pii"]["providers"]["roberta_ner"]["enabled"] is False


def test_enable_does_not_duplicate_existing_chain_entry(
    monkeypatch, tmp_path: Path
) -> None:
    """If the operator clicks Enable while the provider is already in
    the chain (race / stale UI), the patch must not produce duplicate
    entries — the helper de-dupes."""
    _redirect_writer(monkeypatch, tmp_path, "pii:\n  provider_chain:\n    - regex\n")
    current = AppConfig(pii=PIISection(provider_chain=["regex"]))
    # Caller computes patch with regex already in chain.
    patch = _build_enable_patch("pii", "regex", ["regex"])
    response = patch_config(body=patch, current=current)
    assert response["config"]["pii"]["provider_chain"] == ["regex"]
