"""Frozen-aware path resolution (Phase 15.2)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from care.core import paths
from care.core.config import AppConfig


def _set_frozen(monkeypatch, frozen: bool, user_data: Path) -> None:
    """Pretend we're (or aren't) running inside a PyInstaller bundle.

    Patches ``sys.frozen`` AND the runtime_paths.user_data_root override
    via env vars so ``is_frozen()`` reports the chosen state and the
    user-data resolver points at ``user_data``.
    """
    if frozen:
        monkeypatch.setattr(sys, "frozen", True, raising=False)
    else:
        # ``raising=False`` avoids touching frozen if it doesn't exist.
        if hasattr(sys, "frozen"):
            monkeypatch.delattr(sys, "frozen", raising=False)
    # Force user_data_root() to resolve under our tmp dir on every
    # platform by setting platform-appropriate env vars.
    monkeypatch.setenv("LOCALAPPDATA", str(user_data / "AppData" / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(user_data / "share"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: user_data))


def test_work_dir_resolves_under_cwd_in_dev_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    _set_frozen(monkeypatch, frozen=False, user_data=tmp_path / "userdata")
    cfg = AppConfig()
    cfg.paths.work_dir = "./work"
    out = paths.work_dir(cfg)
    assert str(out).startswith(str(tmp_path))


def test_work_dir_resolves_under_user_data_when_frozen(
    monkeypatch, tmp_path: Path
) -> None:
    _set_frozen(monkeypatch, frozen=True, user_data=tmp_path)
    cfg = AppConfig()
    cfg.paths.work_dir = "./work"  # relative — should anchor under user_data
    out = paths.work_dir(cfg)
    # The work dir should be inside SOME platform-appropriate subdir
    # of tmp_path (LOCALAPPDATA / Library / .local/share). All three
    # contain tmp_path as a prefix.
    assert str(out).startswith(str(tmp_path))
    assert out.name == "work"


def test_absolute_path_is_honoured_verbatim_when_frozen(
    monkeypatch, tmp_path: Path
) -> None:
    """Operators that point at an external drive must get exactly
    that path, even in a frozen build."""
    _set_frozen(monkeypatch, frozen=True, user_data=tmp_path / "userdata")
    cfg = AppConfig()
    explicit = (tmp_path / "external" / "work").resolve()
    cfg.paths.work_dir = str(explicit)
    out = paths.work_dir(cfg)
    assert out == explicit


def test_export_dir_lives_under_documents_when_frozen(
    monkeypatch, tmp_path: Path
) -> None:
    """Export dir must default to Documents/CARE/exports
    when frozen — that's where operators look in Explorer."""
    _set_frozen(monkeypatch, frozen=True, user_data=tmp_path)
    cfg = AppConfig()
    cfg.paths.export_dir = "./exports"
    out = paths.export_dir(cfg)
    # On Linux the platform docs dir is $HOME/Documents — we patched
    # Path.home() to tmp_path above, so:
    assert str(out).startswith(str(tmp_path / "Documents"))


def test_templates_and_models_resolve_under_user_data_when_frozen(
    monkeypatch, tmp_path: Path
) -> None:
    _set_frozen(monkeypatch, frozen=True, user_data=tmp_path)
    cfg = AppConfig()
    cfg.paths.templates_dir = "./templates"
    cfg.paths.models_dir = "./models"
    assert paths.templates_dir(cfg).name == "templates"
    assert paths.models_dir(cfg).name == "models"
    # Both should live under SOME user-data tree (which is under tmp).
    assert str(paths.templates_dir(cfg)).startswith(str(tmp_path))
    assert str(paths.models_dir(cfg)).startswith(str(tmp_path))


# ----- config writer ---------------------------------------------------


def test_resolve_write_path_falls_back_to_user_data_when_frozen(
    monkeypatch, tmp_path: Path
) -> None:
    _set_frozen(monkeypatch, frozen=True, user_data=tmp_path)
    from care.core import config_writer

    # No DEFAULT_CONFIG_PATHS file exists in tmp; fallback path applies.
    monkeypatch.setattr(
        config_writer, "DEFAULT_CONFIG_PATHS", []
    )
    out = config_writer.resolve_write_path()
    assert "config" in str(out) and out.name == "config.yaml"
    assert str(out).startswith(str(tmp_path))


def test_resolve_write_path_falls_back_to_cwd_in_dev_mode(
    monkeypatch, tmp_path: Path
) -> None:
    _set_frozen(monkeypatch, frozen=False, user_data=tmp_path / "userdata")
    monkeypatch.chdir(tmp_path)
    from care.core import config_writer

    monkeypatch.setattr(config_writer, "DEFAULT_CONFIG_PATHS", [])
    out = config_writer.resolve_write_path()
    assert out == (tmp_path / "config.yaml").resolve()
