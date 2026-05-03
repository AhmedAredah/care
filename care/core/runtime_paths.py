"""Per-platform path resolution for frozen and dev builds (Phase 15.1).

The repo is run two distinct ways:

- **dev / source checkout**: ``python -m care.cli ...`` from the
  repo root. ``cwd`` IS the install dir; relative paths in
  ``config.yaml`` (``./work``, ``./templates``, etc.) resolve naturally.
- **frozen Windows / macOS install**: a PyInstaller-bundled binary
  launched from anywhere. ``cwd`` is whatever the OS / shortcut sets
  it to (often ``C:\\Windows\\System32`` on Windows). Relative paths
  break. Program Files is read-only. We need an explicit, per-user
  data root.

This module is the single source of truth for "where does a runtime
file go?". Two consumers depend on it:

- :mod:`care.core.config` — extends ``DEFAULT_CONFIG_PATHS``
  with the user-data location so the GUI Settings page reads/writes
  the same file the next ``serve`` will pick up.
- :mod:`care.cli.bootstrap` — copies bundled defaults into
  the user-data dir on first launch.

Layout per platform (constants below)::

    Windows: %LOCALAPPDATA%\\CARE\\
    macOS:   ~/Library/Application Support/CARE/
    Linux:   $XDG_DATA_HOME/care/  (defaults to
             ~/.local/share/care/)

Subdirectories under that root::

    config/       config.yaml + .bak files
    secrets/      secrets.yaml (ACL: current user only)
    templates/    user-customised templates (override the bundle)
    models/       operator-placed model weights
    work/         pipeline scratch + WebView cache
    logs/         rotating log files

User-discoverable output (redacted exports) lives separately under
the user's Documents folder so it shows up where they expect to look:

    Windows: %USERPROFILE%\\Documents\\CARE\\exports\\
    macOS:   ~/Documents/CARE/exports/
    Linux:   $XDG_DOCUMENTS_DIR/CARE/exports/  (or
             ~/Documents if XDG isn't configured)
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

_log = logging.getLogger(__name__)

# Subdirectory names — kept here so consumers reference one source.
SUBDIR_CONFIG = "config"
SUBDIR_SECRETS = "secrets"
SUBDIR_TEMPLATES = "templates"
SUBDIR_MODELS = "models"
SUBDIR_WORK = "work"
SUBDIR_LOGS = "logs"
SUBDIR_EXPORTS = "exports"  # under Documents, not under data root

# App identifier appearing in directory names. Spaces on macOS where
# users see it in Finder; lowercased+hyphenated on Linux to match
# XDG conventions.
_APP_DIR_WINDOWS = "CARE"
_APP_DIR_MACOS = "CARE"
_APP_DIR_LINUX = "care"
_DOCUMENTS_DIR_NAME = "CARE"


def is_frozen() -> bool:
    """True when running inside a PyInstaller / Nuitka / cx_Freeze bundle."""
    return bool(getattr(sys, "frozen", False))


def bundled_resource_root() -> Path:
    """Where read-only bundled resources live.

    - In a PyInstaller onedir / onefile build, ``sys._MEIPASS`` points at
      the unpacked bundle (frontend, templates, assets, the seed
      ``config.template.yaml``).
    - In a dev checkout, that's the repo root.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    # Module path: care/core/runtime_paths.py → repo root is parents[2].
    return Path(__file__).resolve().parents[2]


def _detect_platform() -> str:
    """Return the platform tag this resolver branches on.

    One of: ``"windows"``, ``"macos"``, ``"linux"``. Linux is the
    fallback bucket — covers POSIX systems we don't explicitly handle.
    """
    if os.name == "nt":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def user_data_root(
    *,
    override: Optional[Path] = None,
    platform_tag: Optional[str] = None,
) -> Path:
    """Per-user data root.

    ``override`` short-circuits the resolver entirely (for tests that
    want to point at a tmp_path). ``platform_tag`` lets tests force
    a non-host branch (``"windows"`` / ``"macos"`` / ``"linux"``)
    without monkey-patching ``os.name`` — which breaks pytest's own
    pathlib usage.
    """
    if override is not None:
        return Path(override).resolve()
    tag = platform_tag or _detect_platform()
    if tag == "windows":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / _APP_DIR_WINDOWS
        return Path.home() / "AppData" / "Local" / _APP_DIR_WINDOWS
    if tag == "macos":
        return Path.home() / "Library" / "Application Support" / _APP_DIR_MACOS
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / _APP_DIR_LINUX


def user_documents_root(*, override: Optional[Path] = None) -> Path:
    """User-discoverable output dir (under Documents on every platform)."""
    if override is not None:
        return Path(override).resolve()
    docs = _platform_documents_dir()
    return docs / _DOCUMENTS_DIR_NAME


def _platform_documents_dir() -> Path:
    """Best-effort resolver for the user's Documents folder.

    On Windows we ask the shell for FOLDERID_Documents via ctypes,
    because the user may have redirected ``%USERPROFILE%\\Documents``
    to OneDrive or a network share.
    """
    if os.name == "nt":
        try:
            return _windows_known_folder_documents()
        except Exception:  # noqa: BLE001
            return Path.home() / "Documents"
    # macOS + Linux: $HOME/Documents is the conventional default. We do
    # not parse Linux's xdg-user-dirs because it's an extra dep and the
    # /Documents fallback is universally correct enough.
    return Path.home() / "Documents"


def _windows_known_folder_documents() -> Path:
    """Resolve ``FOLDERID_Documents`` via SHGetKnownFolderPath."""
    import ctypes
    from ctypes import wintypes

    FOLDERID_DOCUMENTS = ctypes.c_char_p(
        b"\xd0\x6c\xb6\xfd\x4d\xea\xb9\x40\x91\x46\xdb\x6c\x43\x9c\x05\xc1"
    )
    _ = FOLDERID_DOCUMENTS  # keep ref alive
    # The proper way: use GUID struct. Here we use a hand-built blob.
    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    documents_guid = GUID(
        0xFDD06CB6, 0xEA4D, 0x40B9,
        (ctypes.c_ubyte * 8)(0x91, 0x46, 0xDB, 0x6C, 0x43, 0x9C, 0x05, 0xC1),
    )
    SHGetKnownFolderPath = ctypes.windll.shell32.SHGetKnownFolderPath
    SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    SHGetKnownFolderPath.restype = ctypes.HRESULT
    out = ctypes.c_wchar_p()
    rc = SHGetKnownFolderPath(
        ctypes.byref(documents_guid), 0, None, ctypes.byref(out)
    )
    if rc != 0 or not out.value:
        raise OSError(f"SHGetKnownFolderPath returned {rc}")
    try:
        return Path(out.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


# ----- subdir helpers --------------------------------------------------


def config_dir(*, override: Optional[Path] = None) -> Path:
    return user_data_root(override=override) / SUBDIR_CONFIG


def secrets_dir(*, override: Optional[Path] = None) -> Path:
    return user_data_root(override=override) / SUBDIR_SECRETS


def templates_user_dir(*, override: Optional[Path] = None) -> Path:
    return user_data_root(override=override) / SUBDIR_TEMPLATES


def models_dir(*, override: Optional[Path] = None) -> Path:
    return user_data_root(override=override) / SUBDIR_MODELS


def work_dir(*, override: Optional[Path] = None) -> Path:
    return user_data_root(override=override) / SUBDIR_WORK


def logs_dir(*, override: Optional[Path] = None) -> Path:
    return user_data_root(override=override) / SUBDIR_LOGS


def exports_dir(*, override: Optional[Path] = None) -> Path:
    return user_documents_root(override=override) / SUBDIR_EXPORTS


def all_subdirs(*, override: Optional[Path] = None) -> dict[str, Path]:
    """Return every managed dir keyed by its short name."""
    return {
        SUBDIR_CONFIG: config_dir(override=override),
        SUBDIR_SECRETS: secrets_dir(override=override),
        SUBDIR_TEMPLATES: templates_user_dir(override=override),
        SUBDIR_MODELS: models_dir(override=override),
        SUBDIR_WORK: work_dir(override=override),
        SUBDIR_LOGS: logs_dir(override=override),
    }


# ----- bootstrap (first-run defaults) ---------------------------------


def is_first_run(*, override: Optional[Path] = None) -> bool:
    """True iff user-data dir doesn't have a config file yet."""
    return not (config_dir(override=override) / "config.yaml").exists()


def bootstrap_user_data(
    *,
    override: Optional[Path] = None,
    bundle_root: Optional[Path] = None,
    seed_config_name: str = "config.yaml",
) -> dict[str, Path]:
    """Create user-data subdirs + seed config from the bundle.

    Idempotent: re-running on an already-bootstrapped install is a
    no-op. Returns the mapping of subdirs (same shape as
    :func:`all_subdirs`).

    The seed config is copied from ``<bundle>/<seed_config_name>``.
    Defaults to ``config.yaml`` so a dev checkout uses its own
    in-tree config; frozen builds ship ``config.yaml`` (the
    sanitised default) inside the bundle.
    """
    bundle = bundle_root or bundled_resource_root()
    subdirs = all_subdirs(override=override)
    for sub in subdirs.values():
        sub.mkdir(parents=True, exist_ok=True)
    cfg_target = subdirs[SUBDIR_CONFIG] / "config.yaml"
    if not cfg_target.exists():
        seed = bundle / seed_config_name
        if seed.exists():
            cfg_target.write_bytes(seed.read_bytes())
        else:
            _log.warning(
                "no seed config found at %s; user must create config.yaml",
                seed,
            )
    # Templates: copy any *.yaml from bundle that the user dir doesn't have.
    bundle_templates = bundle / "templates"
    if bundle_templates.is_dir():
        for src in bundle_templates.rglob("*.yaml"):
            rel = src.relative_to(bundle_templates)
            target = subdirs[SUBDIR_TEMPLATES] / rel
            if target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(src.read_bytes())
    return subdirs
