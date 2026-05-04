"""Cross-platform desktop-shortcut installer (Phase 14.2).

These tests never touch the operator's real Desktop. We point each
installer at a tmp_path-rooted "Desktop" and assert the artefacts
that *would* land on a real install actually get written there.

Some assertions are POSIX-only (chmod's executable bit is a no-op on
NTFS — Python's ``os.chmod`` only honours the read-only flag on
Windows). Those tests are guarded with ``skipif sys.platform == 'win32'``
so they run on macOS / Linux CI but skip on a Windows dev machine
running the full suite locally. The functions themselves are still
callable on Windows; we just can't observe a meaningful x-bit there.
"""
from __future__ import annotations

import plistlib
import stat
import sys
from pathlib import Path

import pytest

from care.cli import shortcut

_WINDOWS_NO_XBIT = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX executable bit is a no-op on NTFS; the chmod call "
    "still runs but Python's os.chmod can't set S_IXUSR.",
)


# ----- shared helpers --------------------------------------------------


def test_build_command_args_includes_config_when_given() -> None:
    config = Path("/abs/config.yaml")
    args = shortcut._build_command_args(config)
    assert "-m" in args and "care.cli" in args and "app" in args
    # Compare against ``str(config)`` so the assertion is stable across
    # platforms — on Windows ``str(WindowsPath("/abs/config.yaml"))``
    # is ``"\\abs\\config.yaml"``, and the literal POSIX form would
    # never appear in argv there.
    assert "--config" in args and str(config) in args


def test_build_command_args_omits_config_when_none() -> None:
    args = shortcut._build_command_args(None)
    assert "--config" not in args


def test_install_root_uses_explicit_when_given(tmp_path: Path) -> None:
    explicit = tmp_path / "deployment"
    explicit.mkdir()
    assert shortcut._install_root(explicit) == explicit.resolve()


def test_install_root_falls_back_to_repo_root() -> None:
    """The fallback should be the directory containing pyproject.toml."""
    root = shortcut._install_root(None)
    assert (root / "pyproject.toml").exists()


def test_shell_quote_escapes_embedded_quotes() -> None:
    out = shortcut._shell_quote("path with 'quote'")
    assert out.startswith("'") and out.endswith("'")
    # The single quote in the middle is escaped via the standard
    # POSIX 'quote'\''quote' trick.
    assert "'\\''" in out


# ----- macOS -----------------------------------------------------------


def test_install_macos_creates_app_bundle_with_run_script(tmp_path: Path) -> None:
    bundle = shortcut.install_macos(
        config_path=tmp_path / "config.yaml",
        install_root=tmp_path / "install-root",
        desktop_dir=tmp_path,
    )
    assert bundle.is_dir()
    run_script = bundle / "Contents" / "MacOS" / "run"
    assert run_script.is_file()
    text = run_script.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/bash")
    assert "care.cli" in text
    assert "--config" in text


@_WINDOWS_NO_XBIT
def test_install_macos_run_script_is_executable(tmp_path: Path) -> None:
    bundle = shortcut.install_macos(desktop_dir=tmp_path)
    run_script = bundle / "Contents" / "MacOS" / "run"
    mode = run_script.stat().st_mode
    assert mode & stat.S_IXUSR


def test_install_macos_writes_plist(tmp_path: Path) -> None:
    bundle = shortcut.install_macos(desktop_dir=tmp_path)
    plist_path = bundle / "Contents" / "Info.plist"
    with plist_path.open("rb") as fh:
        data = plistlib.load(fh)
    assert data["CFBundleExecutable"] == "run"
    assert data["CFBundlePackageType"] == "APPL"
    assert data["CFBundleName"] == shortcut.APP_NAME


def test_install_macos_copies_icon_when_given(tmp_path: Path) -> None:
    icon = tmp_path / "icon.icns"
    icon.write_bytes(b"\x00\x00\x00\x00fake-icns")
    bundle = shortcut.install_macos(icon_path=icon, desktop_dir=tmp_path)
    target_icon = bundle / "Contents" / "Resources" / "icon.icns"
    assert target_icon.exists()
    plist = plistlib.loads((bundle / "Contents" / "Info.plist").read_bytes())
    assert plist.get("CFBundleIconFile") == "icon"


def test_uninstall_macos_removes_bundle(tmp_path: Path) -> None:
    shortcut.install_macos(desktop_dir=tmp_path)
    assert shortcut.uninstall_macos(desktop_dir=tmp_path) is True
    assert not (tmp_path / shortcut.LAUNCHER_FILENAME["Darwin"]).exists()


def test_uninstall_macos_returns_false_when_missing(tmp_path: Path) -> None:
    assert shortcut.uninstall_macos(desktop_dir=tmp_path) is False


# ----- Linux -----------------------------------------------------------


def test_install_linux_writes_apps_and_desktop(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    apps_file, desktop_file = shortcut.install_linux(
        config_path=tmp_path / "config.yaml",
        desktop_dir=tmp_path,
    )
    assert apps_file.is_file()
    assert desktop_file.is_file()
    text = apps_file.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in text
    assert "Type=Application" in text
    assert "care.cli" in text
    assert "--config" in text


@_WINDOWS_NO_XBIT
def test_install_linux_marks_files_executable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    apps_file, _ = shortcut.install_linux(desktop_dir=tmp_path)
    mode = apps_file.stat().st_mode
    assert mode & stat.S_IXUSR


def test_install_linux_uses_xdg_data_home_when_set(
    monkeypatch, tmp_path: Path
) -> None:
    custom = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(custom))
    apps_file, _ = shortcut.install_linux(desktop_dir=tmp_path)
    assert str(apps_file).startswith(str(custom))


def test_uninstall_linux_removes_both_copies(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    shortcut.install_linux(desktop_dir=tmp_path)
    assert shortcut.uninstall_linux(desktop_dir=tmp_path) is True
    apps_file = tmp_path / "share" / "applications" / shortcut.LAUNCHER_FILENAME["Linux"]
    assert not apps_file.exists()
    assert not (tmp_path / shortcut.LAUNCHER_FILENAME["Linux"]).exists()


# ----- Windows ---------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode: int = 0, stderr: str = "") -> None:
        self.returncode = returncode
        self.stderr = stderr


def test_install_windows_invokes_powershell_with_lnk_path(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv, *args, **kwargs):
        captured["argv"] = argv
        # Simulate the .lnk being created by PowerShell.
        lnk = tmp_path / shortcut.LAUNCHER_FILENAME["Windows"]
        lnk.write_bytes(b"fake-lnk")
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr(shortcut.subprocess, "run", fake_run)
    lnk = shortcut.install_windows(
        config_path=tmp_path / "config.yaml",
        desktop_dir=tmp_path,
    )
    assert lnk.exists()
    argv = captured["argv"]
    assert argv[0] == "powershell"
    script = argv[-1]
    # PowerShell snippet must mention WshShell and the lnk path.
    assert "WshShell" in script
    assert "TargetPath" in script
    # Backslash-doubled path should appear in the script.
    assert "CARE.lnk" in script


def test_install_windows_propagates_powershell_failure(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        shortcut.subprocess,
        "run",
        lambda *a, **kw: _FakeCompleted(returncode=1, stderr="bad"),
    )
    with pytest.raises(RuntimeError, match="PowerShell failed"):
        shortcut.install_windows(desktop_dir=tmp_path)


def test_uninstall_windows_removes_lnk(tmp_path: Path) -> None:
    lnk = tmp_path / shortcut.LAUNCHER_FILENAME["Windows"]
    lnk.write_bytes(b"fake")
    assert shortcut.uninstall_windows(desktop_dir=tmp_path) is True
    assert not lnk.exists()


def test_uninstall_windows_returns_false_when_missing(tmp_path: Path) -> None:
    assert shortcut.uninstall_windows(desktop_dir=tmp_path) is False


# ----- dispatch --------------------------------------------------------


def test_install_shortcut_dispatches_per_platform(monkeypatch, tmp_path: Path) -> None:
    """The dispatcher must select the right installer based on
    ``platform.system()`` (overridable for tests)."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    out = shortcut.install_shortcut(system="Linux", desktop_dir=tmp_path)
    assert isinstance(out, tuple)
    assert len(out) == 2

    out2 = shortcut.install_shortcut(system="Darwin", desktop_dir=tmp_path)
    assert Path(out2).is_dir()


def test_install_shortcut_rejects_unknown_platform(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="unsupported platform"):
        shortcut.install_shortcut(system="Solaris", desktop_dir=tmp_path)


def test_uninstall_shortcut_rejects_unknown_platform() -> None:
    with pytest.raises(RuntimeError, match="unsupported platform"):
        shortcut.uninstall_shortcut(system="Solaris")


# ----- icon auto-detection ---------------------------------------------


def test_default_icon_for_system_returns_existing_asset() -> None:
    """If the asset exists in the repo, the default-icon helper should
    point at it. We have icon.ico / .icns / .png committed under
    assets/ as part of Phase 14.3."""
    win = shortcut.default_icon_for_system("Windows")
    mac = shortcut.default_icon_for_system("Darwin")
    lin = shortcut.default_icon_for_system("Linux")
    # All three must resolve in the in-tree checkout.
    assert win is not None and win.exists()
    assert mac is not None and mac.exists()
    assert lin is not None and lin.exists()


def test_default_icon_for_unknown_system_returns_none() -> None:
    assert shortcut.default_icon_for_system("Solaris") is None


def test_install_shortcut_uses_auto_icon_when_not_supplied(
    monkeypatch, tmp_path: Path
) -> None:
    """install_shortcut should fall back to default_icon_for_system
    when the operator omits --icon."""
    captured: dict[str, object] = {}

    def fake_install_macos(**kwargs):
        captured.update(kwargs)
        bundle = (kwargs["desktop_dir"]) / shortcut.LAUNCHER_FILENAME["Darwin"]
        bundle.mkdir(parents=True, exist_ok=True)
        return bundle

    monkeypatch.setattr(shortcut, "install_macos", fake_install_macos)
    shortcut.install_shortcut(system="Darwin", desktop_dir=tmp_path)
    icon = captured["icon_path"]
    assert icon is not None
    assert icon.suffix == ".icns"
