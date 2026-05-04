"""Desktop-shortcut installer (Phase 14.2).

End users run::

    care install-shortcut

once after install; a platform-appropriate launcher lands on their
Desktop and points at::

    <python> -m care.cli app --config <abs-path-to-config>

with ``cwd`` set to the install root so ``config.yaml`` and
``secrets.yaml`` always live in a predictable place.

Three implementations:

- **Windows**: a ``.lnk`` shell shortcut. Built via ``win32com``
  when available (the same module already used by other DOT
  tooling); fall back to a small PowerShell snippet so we don't
  hard-fail when pywin32 isn't installed.
- **macOS**: an ``.app`` bundle (a directory with ``Info.plist`` +
  ``Contents/MacOS/run``). Stdlib only.
- **Linux**: an XDG ``.desktop`` file in
  ``~/.local/share/applications/`` plus a copy on
  ``~/Desktop`` for one-click launch.

Idempotent: re-running overwrites cleanly. ``uninstall_*``
counterparts remove the artefacts.

The installer runs with the user's permissions only — never
escalates, never writes outside ``$HOME``, never edits the
registry / installs services.
"""
from __future__ import annotations

import logging
import os
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

_log = logging.getLogger(__name__)

APP_NAME = "CARE"
LAUNCHER_FILENAME = {
    "Windows": "CARE.lnk",
    "Darwin": "CARE.app",
    "Linux": "care.desktop",
}

# Per-platform icon filenames inside the repo's ``assets/`` dir.
_DEFAULT_ICON_BY_SYSTEM = {
    "Windows": "icon.ico",
    "Darwin": "icon.icns",
    "Linux": "icon.png",
}


def default_icon_for_system(sysname: str) -> Path | None:
    """Return the bundled-asset icon path for ``sysname``, if it exists."""
    filename = _DEFAULT_ICON_BY_SYSTEM.get(sysname)
    if not filename:
        return None
    repo_root = _install_root(None)
    candidate = repo_root / "assets" / filename
    return candidate if candidate.exists() else None


# ----- shared helpers --------------------------------------------------


def _desktop_dir() -> Path:
    """Return the user's Desktop. Falls back to ``$HOME`` if missing."""
    home = Path.home()
    candidate = home / "Desktop"
    return candidate if candidate.is_dir() else home


def _python_executable() -> str:
    """Pick the Python the launcher should invoke.

    Prefer ``sys.executable`` so the shortcut targets the same
    interpreter that ran ``install-shortcut`` (i.e., the virtualenv
    the operator just configured).
    """
    return sys.executable


def _install_root(explicit: Path | None = None) -> Path:
    """Working directory the launcher should set as ``cwd``.

    Defaults to the parent of the running CLI module's package — that
    is the repository root, where ``config.yaml`` lives in dev. When
    operators install via the offline installer this will resolve to
    whatever directory the wheelhouse was unpacked into.
    """
    if explicit is not None:
        return Path(explicit).resolve()
    here = Path(__file__).resolve()
    # care/cli/shortcut.py → repo root is parents[2].
    return here.parents[2]


def _build_command_args(config_path: Path | None) -> list[str]:
    """argv for the launcher, minus the python executable."""
    argv = ["-m", "care.cli", "app"]
    if config_path is not None:
        argv.extend(["--config", str(config_path)])
    return argv


# ----- Windows ---------------------------------------------------------


_WINDOWS_PS_TEMPLATE = textwrap.dedent(
    r"""
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut("{lnk}")
    $Shortcut.TargetPath = "{target}"
    $Shortcut.Arguments = '{args}'
    $Shortcut.WorkingDirectory = "{cwd}"
    $Shortcut.WindowStyle = 7
    $Shortcut.Description = "CARE — desktop launcher"
    {icon_line}
    $Shortcut.Save()
    """
).strip()


def install_windows(
    *,
    config_path: Path | None = None,
    install_root: Path | None = None,
    icon_path: Path | None = None,
    desktop_dir: Path | None = None,
) -> Path:
    """Create ``Desktop\\CARE.lnk``."""
    desktop = (desktop_dir or _desktop_dir()).resolve()
    cwd = _install_root(install_root)
    target = _python_executable()
    cmd_args = _build_command_args(config_path)
    quoted_args = " ".join(_quote_for_powershell(a) for a in cmd_args)
    lnk = (desktop / LAUNCHER_FILENAME["Windows"]).resolve()
    icon_line = (
        f'$Shortcut.IconLocation = "{icon_path}"' if icon_path else ""
    )
    script = _WINDOWS_PS_TEMPLATE.format(
        lnk=str(lnk).replace("\\", "\\\\"),
        target=str(target).replace("\\", "\\\\"),
        args=quoted_args,
        cwd=str(cwd).replace("\\", "\\\\"),
        icon_line=icon_line,
    )
    _run_powershell(script)
    if not lnk.exists():
        raise RuntimeError(f"PowerShell finished but {lnk} was not created")
    return lnk


def _quote_for_powershell(value: str) -> str:
    """Wrap a token in double quotes if it contains spaces."""
    if any(c.isspace() for c in value):
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _run_powershell(script: str) -> None:
    """Run a script via ``powershell.exe -NoProfile``.

    PowerShell is part of every supported Windows version since 7;
    ``win32com`` would be cleaner but adds a dep that's already
    optional. Keeping the implementation pure-stdlib means the
    shortcut installer works on a vanilla Python install.
    """
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-Command", script,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"PowerShell failed (rc={completed.returncode}): "
            f"{completed.stderr.strip()}"
        )


def uninstall_windows(*, desktop_dir: Path | None = None) -> bool:
    """Remove the .lnk if present. Returns True iff something deleted."""
    desktop = (desktop_dir or _desktop_dir()).resolve()
    lnk = desktop / LAUNCHER_FILENAME["Windows"]
    if not lnk.exists():
        return False
    lnk.unlink()
    return True


# ----- macOS -----------------------------------------------------------


def install_macos(
    *,
    config_path: Path | None = None,
    install_root: Path | None = None,
    icon_path: Path | None = None,
    desktop_dir: Path | None = None,
) -> Path:
    """Create ``Desktop/CARE.app`` (a directory bundle)."""
    desktop = (desktop_dir or _desktop_dir()).resolve()
    cwd = _install_root(install_root)
    target = _python_executable()
    cmd_args = _build_command_args(config_path)

    bundle = (desktop / LAUNCHER_FILENAME["Darwin"]).resolve()
    macos_dir = bundle / "Contents" / "MacOS"
    resources_dir = bundle / "Contents" / "Resources"
    macos_dir.mkdir(parents=True, exist_ok=True)
    resources_dir.mkdir(parents=True, exist_ok=True)

    script = macos_dir / "run"
    script.write_text(
        _build_macos_run_script(target, cmd_args, cwd),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    plist_path = bundle / "Contents" / "Info.plist"
    plist_data = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": "org.opencrashextract.desktop",
        "CFBundleExecutable": "run",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "10.13",
        "NSHighResolutionCapable": True,
    }
    if icon_path is not None:
        target_icon = resources_dir / "icon.icns"
        shutil.copy2(icon_path, target_icon)
        plist_data["CFBundleIconFile"] = "icon"

    with plist_path.open("wb") as fh:
        plistlib.dump(plist_data, fh)
    return bundle


def _build_macos_run_script(
    python: str, cmd_args: list[str], cwd: Path
) -> str:
    quoted = " ".join(_shell_quote(a) for a in cmd_args)
    return (
        "#!/bin/bash\n"
        f"cd {_shell_quote(str(cwd))}\n"
        f"exec {_shell_quote(python)} {quoted}\n"
    )


def _shell_quote(value: str) -> str:
    """Single-quote a token for POSIX shell, escaping embedded quotes."""
    return "'" + value.replace("'", "'\\''") + "'"


def uninstall_macos(*, desktop_dir: Path | None = None) -> bool:
    desktop = (desktop_dir or _desktop_dir()).resolve()
    bundle = desktop / LAUNCHER_FILENAME["Darwin"]
    if not bundle.exists():
        return False
    if bundle.is_dir():
        shutil.rmtree(bundle)
    else:
        bundle.unlink()
    return True


# ----- Linux -----------------------------------------------------------


def _xdg_applications_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "applications"


def install_linux(
    *,
    config_path: Path | None = None,
    install_root: Path | None = None,
    icon_path: Path | None = None,
    desktop_dir: Path | None = None,
) -> tuple[Path, Path]:
    """Write the .desktop file under ``$XDG_DATA_HOME/applications``.

    Also drops a copy on the user's Desktop so it's discoverable by
    DEs that don't show app-menu entries on the desktop.

    Returns ``(applications_path, desktop_path)``.
    """
    cwd = _install_root(install_root)
    target = _python_executable()
    cmd_args = _build_command_args(config_path)

    apps_dir = _xdg_applications_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)
    apps_file = apps_dir / LAUNCHER_FILENAME["Linux"]
    apps_file.write_text(
        _build_linux_desktop_entry(target, cmd_args, cwd, icon_path),
        encoding="utf-8",
    )
    apps_file.chmod(apps_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)

    desktop = (desktop_dir or _desktop_dir()).resolve()
    desktop_file = desktop / LAUNCHER_FILENAME["Linux"]
    if desktop.exists():
        desktop_file.write_text(apps_file.read_text(encoding="utf-8"), encoding="utf-8")
        desktop_file.chmod(
            desktop_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
        )

    return apps_file, desktop_file


def _build_linux_desktop_entry(
    python: str, cmd_args: list[str], cwd: Path, icon_path: Path | None
) -> str:
    exec_line = " ".join([_shell_quote(python)] + [_shell_quote(a) for a in cmd_args])
    icon_field = (
        f"Icon={icon_path}\n" if icon_path else ""
    )
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Comment={APP_NAME} — desktop launcher\n"
        f"Exec={exec_line}\n"
        f"Path={cwd}\n"
        f"{icon_field}"
        "Terminal=false\n"
        "Categories=Office;Utility;\n"
    )


def uninstall_linux(*, desktop_dir: Path | None = None) -> bool:
    """Remove both copies of the .desktop entry, if present."""
    removed = False
    apps_file = _xdg_applications_dir() / LAUNCHER_FILENAME["Linux"]
    if apps_file.exists():
        apps_file.unlink()
        removed = True
    desktop = (desktop_dir or _desktop_dir()).resolve()
    desktop_file = desktop / LAUNCHER_FILENAME["Linux"]
    if desktop_file.exists():
        desktop_file.unlink()
        removed = True
    return removed


# ----- dispatch --------------------------------------------------------


def install_shortcut(
    *,
    config_path: Path | None = None,
    install_root: Path | None = None,
    icon_path: Path | None = None,
    desktop_dir: Path | None = None,
    system: str | None = None,
) -> object:
    """Pick the right installer for the running platform.

    ``system`` is exposed for tests so they can exercise every code
    path on a single host. In production it defaults to
    :func:`platform.system`.
    """
    sysname = system or platform.system()
    if icon_path is None:
        icon_path = default_icon_for_system(sysname)
    kwargs = {
        "config_path": config_path,
        "install_root": install_root,
        "icon_path": icon_path,
        "desktop_dir": desktop_dir,
    }
    if sysname == "Windows":
        return install_windows(**kwargs)
    if sysname == "Darwin":
        return install_macos(**kwargs)
    if sysname == "Linux":
        return install_linux(**kwargs)
    raise RuntimeError(f"unsupported platform for shortcut: {sysname!r}")


def uninstall_shortcut(
    *, desktop_dir: Path | None = None, system: str | None = None
) -> bool:
    sysname = system or platform.system()
    if sysname == "Windows":
        return uninstall_windows(desktop_dir=desktop_dir)
    if sysname == "Darwin":
        return uninstall_macos(desktop_dir=desktop_dir)
    if sysname == "Linux":
        return uninstall_linux(desktop_dir=desktop_dir)
    raise RuntimeError(f"unsupported platform for shortcut: {sysname!r}")
