"""Resolve and create the working directories declared in AppConfig."""
from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from .config import AppConfig

_WINDOWS_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/](.*)", re.DOTALL)


def _host_is_windows() -> bool:
    """Indirection over ``os.name`` so tests can spoof platform without
    touching the global ``os.name`` (which pathlib reads at multiple
    points and which breaks pytest's cache writer on Windows when
    flipped mid-session).
    """
    return os.name == "nt"


def is_absolute_cross_platform(path_str: str) -> bool:
    """Return True if ``path_str`` is absolute under any common convention.

    Recognises:
    - POSIX absolute paths (``/foo/bar``)
    - Windows drive paths (``C:\\foo``, ``c:/foo``)
    - Windows UNC paths (``\\\\server\\share\\foo``)

    The host's own ``Path(...).is_absolute()`` is OS-specific —
    on Linux it rejects ``C:\\Users\\X``, on Windows it rejects POSIX
    paths beginning with ``/``. This helper accepts either.
    """
    if not isinstance(path_str, str) or not path_str:
        return False
    if PurePosixPath(path_str).is_absolute():
        return True
    if PureWindowsPath(path_str).is_absolute():
        return True
    return False


def _looks_like_windows_path(path_str: str) -> bool:
    if not path_str:
        return False
    return bool(_WINDOWS_DRIVE_RE.match(path_str)) or path_str.startswith("\\\\")


def _translate_windows_to_wsl(path_str: str) -> str | None:
    """Map ``C:\\Users\\X`` to ``/mnt/c/Users/X`` when running under
    WSL/Linux. Returns the translated path only if the result actually
    exists on disk; otherwise returns None so the caller can decide.
    UNC paths are not translated (no portable WSL mount convention)."""
    m = _WINDOWS_DRIVE_RE.match(path_str)
    if not m:
        return None
    drive = m.group(1).lower()
    rest = m.group(2).replace("\\", "/")
    candidate = f"/mnt/{drive}/{rest}"
    if Path(candidate).exists():
        return candidate
    return None


def _strip_surrounding_quotes(value: str) -> str:
    """Strip a single matched pair of surrounding ASCII or curly quotes.

    Common slip when copying paths from Windows Explorer / shell:
    the value ends up wrapped like ``"C:\\Users\\X"``. We strip a
    single matched pair so the validator sees the bare path. Internal
    quotes are preserved.
    """
    if not value:
        return value
    pairs = (
        ('"', '"'),
        ("'", "'"),
        ("“", "”"),  # curly “ ”
        ("‘", "’"),  # curly ‘ ’
    )
    for opener, closer in pairs:
        if len(value) >= 2 and value[0] == opener and value[-1] == closer:
            return value[1:-1]
    return value


def normalize_input_path(path_str: str) -> Path:
    """Coerce a user-supplied path string into a host-usable :class:`Path`.

    Trims surrounding whitespace and a single matched pair of quotes
    (operators commonly paste paths copied with quotes from Windows
    Explorer or PowerShell). Then validates that the input is absolute
    (cross-platform). On Linux, a Windows-style drive path is
    translated to its ``/mnt/<drive>/...`` WSL equivalent if such a
    path exists on disk; otherwise the original is returned and the
    caller's ``.exists()`` check produces a clear 404.

    Raises ``ValueError`` if ``path_str`` is not absolute under any
    convention.
    """
    if isinstance(path_str, str):
        path_str = _strip_surrounding_quotes(path_str.strip())
    if not is_absolute_cross_platform(path_str):
        raise ValueError("path must be absolute")
    if not _host_is_windows() and _looks_like_windows_path(path_str):
        translated = _translate_windows_to_wsl(path_str)
        if translated is not None:
            return Path(translated)
        # Fall through with a Path that won't resolve — caller's
        # .exists() check will raise a clear 404 with the original
        # value preserved for the operator's logs.
    return Path(path_str)


def _resolve_runtime_path(value: str, *, default_subdir: str) -> Path:
    """Resolve a ``cfg.paths.*`` string against the right base.

    Phase 15.2 — frozen builds can't write to ``cwd`` because that's
    typically ``C:\\Windows\\System32`` or a Program Files dir. When
    running frozen and the configured path is *relative*, anchor it
    under the user-data root so writes land in
    ``%LOCALAPPDATA%\\CARE\\<subdir>``.

    Absolute paths are honoured verbatim in both modes so operators
    that explicitly point at a network share or an external disk
    still get what they asked for.
    """
    p = Path(value).expanduser()
    if p.is_absolute():
        return p.resolve()
    from .runtime_paths import is_frozen, user_data_root

    if is_frozen():
        return (user_data_root() / default_subdir).resolve()
    return p.resolve()


def work_dir(cfg: AppConfig, *, create: bool = True) -> Path:
    from .runtime_paths import SUBDIR_WORK

    p = _resolve_runtime_path(cfg.paths.work_dir, default_subdir=SUBDIR_WORK)
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def export_dir(cfg: AppConfig, *, create: bool = True) -> Path:
    from .runtime_paths import SUBDIR_EXPORTS, is_frozen, user_documents_root

    raw = Path(cfg.paths.export_dir).expanduser()
    if raw.is_absolute():
        p = raw.resolve()
    elif is_frozen():
        # Exports live under Documents (user-discoverable), NOT under
        # the user-data root. That's where operators look in Explorer.
        p = (user_documents_root() / SUBDIR_EXPORTS).resolve()
    else:
        p = raw.resolve()
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def templates_dir(cfg: AppConfig) -> Path:
    from .runtime_paths import SUBDIR_TEMPLATES

    return _resolve_runtime_path(
        cfg.paths.templates_dir, default_subdir=SUBDIR_TEMPLATES
    )


def models_dir(cfg: AppConfig) -> Path:
    from .runtime_paths import SUBDIR_MODELS

    return _resolve_runtime_path(
        cfg.paths.models_dir, default_subdir=SUBDIR_MODELS
    )
