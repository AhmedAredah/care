"""AppConfig defaults and YAML loading."""
from __future__ import annotations

from pathlib import Path

from care.core.config import AppConfig, load_config

ROOT = Path(__file__).resolve().parents[2]


def test_default_app_config_is_offline_first() -> None:
    cfg = AppConfig()
    assert cfg.offline.enabled is True
    assert cfg.offline.block_network is True
    assert cfg.server.host == "127.0.0.1"
    assert cfg.server.expose_to_network is False
    assert cfg.export.include_original_pdf is False
    assert cfg.export.include_unredacted_text is False
    assert cfg.export.include_debug_artifacts is False
    assert cfg.logging.redact_pii is True
    assert cfg.logging.log_raw_pii is False
    assert cfg.document_ai.enabled is False


def test_repo_config_yaml_loads_and_keeps_optional_plugins_disabled() -> None:
    cfg = load_config(ROOT / "config.yaml")
    assert cfg.document_ai.enabled is False
    assert cfg.document_ai.providers["kosmos25"]["enabled"] is False
    assert cfg.pii.providers["piiranha"]["enabled"] is False


def test_default_config_path_resolution_returns_repo_config() -> None:
    """When a config.yaml exists at the cwd, load_config picks it up."""
    import os

    cwd = os.getcwd()
    try:
        os.chdir(ROOT)
        cfg = load_config()
        assert cfg.offline.enabled is True
    finally:
        os.chdir(cwd)
