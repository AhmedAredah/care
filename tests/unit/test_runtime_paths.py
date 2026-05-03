"""Per-platform runtime path resolver (Phase 15.1)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from care.core import runtime_paths


# ----- is_frozen -------------------------------------------------------


def test_is_frozen_false_under_pytest() -> None:
    """Pytest is never run from a PyInstaller bundle."""
    assert runtime_paths.is_frozen() is False


def test_is_frozen_true_when_sys_frozen_set(monkeypatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert runtime_paths.is_frozen() is True


# ----- bundled_resource_root ------------------------------------------


def test_bundled_resource_root_dev_checkout_is_repo_root() -> None:
    root = runtime_paths.bundled_resource_root()
    assert (root / "pyproject.toml").exists()
    assert (root / "care").exists()


def test_bundled_resource_root_uses_meipass_when_set(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert runtime_paths.bundled_resource_root() == tmp_path


# ----- user_data_root --------------------------------------------------


def test_user_data_root_override_wins(tmp_path: Path) -> None:
    custom = tmp_path / "elsewhere"
    assert runtime_paths.user_data_root(override=custom) == custom.resolve()


def test_user_data_root_windows_uses_localappdata(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    root = runtime_paths.user_data_root(platform_tag="windows")
    assert root.name == "CARE"
    assert "AppData" in str(root)


def test_user_data_root_windows_falls_back_when_localappdata_missing(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    root = runtime_paths.user_data_root(platform_tag="windows")
    assert "AppData" in str(root) and root.name == "CARE"


def test_user_data_root_macos_uses_application_support(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    root = runtime_paths.user_data_root(platform_tag="macos")
    assert "Library" in str(root)
    assert "Application Support" in str(root)
    assert "CARE" in str(root)


def test_user_data_root_linux_respects_xdg_data_home(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    root = runtime_paths.user_data_root(platform_tag="linux")
    assert root == tmp_path / "share" / "care"


def test_user_data_root_linux_falls_back_to_dot_local_share(monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    root = runtime_paths.user_data_root(platform_tag="linux")
    assert root == tmp_path / ".local" / "share" / "care"


# ----- subdir helpers --------------------------------------------------


def test_subdirs_all_under_user_data_root(tmp_path: Path) -> None:
    subs = runtime_paths.all_subdirs(override=tmp_path)
    for path in subs.values():
        assert str(path).startswith(str(tmp_path))
    expected = {
        runtime_paths.SUBDIR_CONFIG,
        runtime_paths.SUBDIR_SECRETS,
        runtime_paths.SUBDIR_TEMPLATES,
        runtime_paths.SUBDIR_MODELS,
        runtime_paths.SUBDIR_WORK,
        runtime_paths.SUBDIR_LOGS,
    }
    assert set(subs.keys()) == expected


def test_exports_dir_lives_under_documents_not_user_data(tmp_path: Path) -> None:
    """Exports must NOT live under user_data_root — operators expect
    redacted output to appear in their Documents folder."""
    docs = tmp_path / "docs"
    exports = runtime_paths.exports_dir(override=docs)
    assert str(exports).startswith(str(docs))


# ----- bootstrap -------------------------------------------------------


def test_bootstrap_creates_all_subdirs(tmp_path: Path) -> None:
    subs = runtime_paths.bootstrap_user_data(override=tmp_path)
    for path in subs.values():
        assert path.is_dir()


def test_bootstrap_seeds_config_from_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "config.yaml").write_text(
        "# bundled seed\noffline:\n  enabled: true\n", encoding="utf-8"
    )
    user_data = tmp_path / "userdata"
    runtime_paths.bootstrap_user_data(override=user_data, bundle_root=bundle)
    cfg = user_data / "config" / "config.yaml"
    assert cfg.read_text(encoding="utf-8").startswith("# bundled seed")


def test_bootstrap_does_not_overwrite_existing_config(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "config.yaml").write_text("# bundled\n", encoding="utf-8")
    user_data = tmp_path / "userdata"
    (user_data / "config").mkdir(parents=True)
    (user_data / "config" / "config.yaml").write_text(
        "# operator-edited\n", encoding="utf-8"
    )
    runtime_paths.bootstrap_user_data(override=user_data, bundle_root=bundle)
    assert (user_data / "config" / "config.yaml").read_text(encoding="utf-8").startswith(
        "# operator-edited"
    )


def test_bootstrap_copies_bundled_templates(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "templates" / "example_state").mkdir(parents=True)
    (bundle / "templates" / "example_state" / "v1.yaml").write_text(
        "template_id: example\n", encoding="utf-8"
    )
    user_data = tmp_path / "userdata"
    runtime_paths.bootstrap_user_data(override=user_data, bundle_root=bundle)
    target = user_data / "templates" / "example_state" / "v1.yaml"
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith("template_id:")


def test_bootstrap_does_not_overwrite_user_template(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "templates").mkdir(parents=True)
    (bundle / "templates" / "v1.yaml").write_text("# from bundle\n", encoding="utf-8")
    user_data = tmp_path / "userdata"
    (user_data / "templates").mkdir(parents=True)
    (user_data / "templates" / "v1.yaml").write_text(
        "# user-customised\n", encoding="utf-8"
    )
    runtime_paths.bootstrap_user_data(override=user_data, bundle_root=bundle)
    assert (user_data / "templates" / "v1.yaml").read_text(encoding="utf-8").startswith(
        "# user-customised"
    )


def test_is_first_run_true_initially(tmp_path: Path) -> None:
    assert runtime_paths.is_first_run(override=tmp_path) is True


def test_is_first_run_false_after_bootstrap(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "config.yaml").write_text("offline:\n  enabled: true\n", encoding="utf-8")
    user_data = tmp_path / "userdata"
    runtime_paths.bootstrap_user_data(override=user_data, bundle_root=bundle)
    assert runtime_paths.is_first_run(override=user_data) is False
