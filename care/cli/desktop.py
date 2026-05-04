"""Desktop-app launcher (Phase 14.1, extended in 15.5).

Wraps the existing FastAPI ``serve`` command in a native window via
pywebview. Used by ``cmd_app`` in :mod:`care.cli.main`.

Process model
-------------
Two strategies depending on whether we're frozen:

- **Dev (source checkout)**: spawn ``cli serve`` as a subprocess via
  ``Popen([sys.executable, "-m", "care.cli", ...])``. Clean
  separation of signal handlers; survives every dev-machine quirk.
- **Frozen (PyInstaller bundle)**: run uvicorn in a thread inside
  the same process. A subprocess in frozen mode would re-launch the
  bundle's bootstrapper as itself, which on PyInstaller onefile is
  expensive (re-extracts the archive) and on onedir would double the
  process count for no benefit.

Either way pywebview owns the main thread (mandatory on macOS) and
the server runs in the background.

The webview window only ever loads the loopback URL we just bound.
No JS bridge (``js_api`` is not set) — extending the API surface
beyond ``/api/*`` would widen the trust boundary.

Cache
-----
WebView2 (Windows) and WebKitGTK (Linux) keep their own per-user
profile by default, in the user's local-app-data folder. We override
that with ``storage_path`` (with ``private_mode=False`` so it actually
persists) so the cache lives inside our managed ``work_dir`` and is
cleaned up with the rest of the working tree.
"""
from __future__ import annotations

import logging
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

from ..core.config import AppConfig

_log = logging.getLogger(__name__)

# Loopback hosts we are willing to render in the desktop window. The
# ``app`` subcommand never accepts a non-loopback host on purpose.
LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})

DEFAULT_TITLE = "CARE"
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 800

# Stable Windows AppUserModelID. Lets the taskbar group our windows
# under a CARE-specific identity instead of "python.exe" in dev mode,
# and pair them with the installed shortcut's icon. Format follows
# Microsoft's "CompanyName.ProductName" guidance.
APP_USER_MODEL_ID = "AhmedAredah.CARE"


def _resolve_app_icon_paths() -> tuple[Optional[Path], Optional[Path]]:
    """Return (ico_path, png_path) for the bundled app icon, if any.

    Resolves under ``bundled_resource_root() / "assets"`` which works
    both in dev (repo root) and frozen builds (sys._MEIPASS). Returns
    ``None`` for either format that isn't present so callers can
    branch cleanly.
    """
    from ..core.runtime_paths import bundled_resource_root

    base = bundled_resource_root() / "assets"
    ico = base / "icon.ico"
    png = base / "icon.png"
    return (
        ico if ico.exists() else None,
        png if png.exists() else None,
    )


def _set_windows_app_user_model_id(app_id: str = APP_USER_MODEL_ID) -> None:
    """Tell Windows our process belongs to a stable CARE identity.

    Without this call, every pywebview window groups under
    ``python.exe`` in the taskbar and inherits python.exe's icon
    (in dev mode). Setting an explicit AppUserModelID makes Windows
    associate our windows with CARE — which lets the taskbar pair
    them with the installed shortcut's icon and group them
    separately from other Python tools.

    Best-effort: silently no-ops on non-Windows or if shell32 is
    unavailable. Must run BEFORE the first window is created.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError) as exc:  # pragma: no cover - Windows-only
        _log.debug("SetCurrentProcessExplicitAppUserModelID failed: %s", exc)


def _bootstrap_pythonnet_for_winforms() -> bool:
    """Initialise the .NET runtime so ``import clr`` works.

    pywebview's WinForms backend does ``import clr`` at module load
    time. In pythonnet 3.x, ``clr`` is a virtual module whose meta-loader
    is registered by ``pythonnet.load()`` — until that runs, a bare
    ``import clr`` raises ``ModuleNotFoundError: No module named 'clr'``
    and pywebview falls through to its "you must have pythonnet
    installed" error message. The package IS installed; the runtime
    just hasn't been bootstrapped yet.

    Calling ``pythonnet.load()`` here primes the runtime (CoreCLR /
    .NET Framework / Mono per ``PYTHONNET_RUNTIME``, defaulting to
    netfx on Windows) so the subsequent ``import clr`` inside pywebview
    succeeds.

    Returns True on success, False on failure. Non-Windows hosts
    no-op and return True (their pywebview backends don't use clr).
    """
    if sys.platform != "win32":
        return True
    try:
        import pythonnet  # type: ignore[import-not-found]

        pythonnet.load()
        return True
    except Exception as exc:  # noqa: BLE001
        _log.error(
            "pythonnet bootstrap failed (%s); the GUI cannot start. "
            "Confirm .NET runtime is installed and PYTHONNET_RUNTIME "
            "is unset or set to 'netfx' / 'coreclr'.",
            exc,
        )
        return False


def _attach_windows_icon(window_title: str, ico_path: Path) -> None:
    """Set the title-bar + Alt-Tab icon for the running pywebview window.

    pywebview's ``webview.start(icon=...)`` is honoured only on GTK
    and Qt backends; on Windows it's a silent no-op. We drive the
    icon ourselves via Win32 ``LoadImage`` + ``WM_SETICON``.

    In frozen builds the .exe icon set by PyInstaller already wins
    for the pinned-taskbar slot; this hook is the dev-mode fallback
    and the title-bar belt-and-suspenders.

    Best-effort: any failure is logged at debug/warning level and
    does not abort the app.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:  # pragma: no cover
        return

    user32 = ctypes.windll.user32

    # Constants from Winuser.h
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x00000010
    LR_DEFAULTSIZE = 0x00000040
    WM_SETICON = 0x0080
    ICON_SMALL = 0
    ICON_BIG = 1

    user32.LoadImageW.restype = wintypes.HANDLE
    user32.FindWindowW.restype = wintypes.HWND
    user32.SendMessageW.restype = ctypes.c_long

    hicon = user32.LoadImageW(
        None,
        str(ico_path),
        IMAGE_ICON,
        0,
        0,
        LR_LOADFROMFILE | LR_DEFAULTSIZE,
    )
    if not hicon:
        _log.warning("LoadImageW returned NULL for %s", ico_path)
        return

    hwnd = user32.FindWindowW(None, window_title)
    if not hwnd:
        _log.warning(
            "FindWindowW could not locate window titled %r — icon not set",
            window_title,
        )
        return

    user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon)
    user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon)
    _log.info("attached app icon to HWND 0x%x", hwnd)


def _assert_loopback(host: str) -> None:
    """Refuse to bind any non-loopback host inside this module.

    The ``cli app`` command's outer ``run_app`` already validates that
    its ``host`` argument lives in :data:`LOOPBACK_HOSTS` and exits
    with code 2 otherwise. Re-asserting the same constraint here makes
    the guarantee local to every ``socket.bind`` site, so static
    analysis (CodeQL ``py/bind-socket-all-network-interfaces``) can
    see the constraint without tracing every caller.
    """
    if host not in LOOPBACK_HOSTS:
        raise ValueError(
            f"refusing to bind socket to non-loopback host {host!r}; "
            f"the desktop app may only bind to {sorted(LOOPBACK_HOSTS)}."
        )


def find_free_port(preferred: int, host: str = "127.0.0.1") -> int:
    """Return ``preferred`` if it's free, otherwise an OS-assigned port."""
    _assert_loopback(host)
    if _is_port_free(host, preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _is_port_free(host: str, port: int) -> bool:
    # Probe with an exclusive bind — no SO_REUSEADDR. On Windows, two
    # sockets that BOTH set SO_REUSEADDR can share the same port, which
    # would make this helper falsely report "free" when another listener
    # is already bound. We want an honest "is anybody home?" check; if
    # the previous bind is in TIME_WAIT, falling back to an OS-assigned
    # port is the correct outcome.
    _assert_loopback(host)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((host, port))
    except OSError:
        return False
    return True


def wait_for_server(
    base_url: str, *, timeout_s: float = 15.0, interval_s: float = 0.25
) -> bool:
    """Poll ``GET <base_url>/api/health`` until 200, ``timeout_s``, or kill.

    Returns ``True`` once the health endpoint responds, ``False`` if
    the deadline elapses. ``base_url`` must already include scheme +
    host + port and must be loopback (the caller validated it).
    """
    deadline = time.monotonic() + timeout_s
    health_url = base_url.rstrip("/") + "/api/health"
    last_err: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2.0) as response:
                if 200 <= response.status < 300:
                    return True
        except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
            last_err = exc
        time.sleep(interval_s)
    if last_err is not None:
        _log.warning("server health probe never returned 2xx: %s", last_err)
    return False


def _build_serve_argv(
    *, host: str, port: int, config_path: Optional[Path]
) -> list[str]:
    """Argv for the subprocess that runs `cli serve`."""
    argv = [
        sys.executable,
        "-m",
        "care.cli",
        "serve",
        "--host",
        host,
        "--port",
        str(port),
    ]
    if config_path is not None:
        argv.extend(["--config", str(config_path)])
    return argv


def _resolve_user_data_dir(config: AppConfig) -> Path:
    """Webview cache lives inside our work_dir so it's auditable."""
    base = Path(config.paths.work_dir).resolve()
    cache = base / "webview-cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


class _ServerHandle:
    """Uniform interface over subprocess vs threaded uvicorn.

    Both strategies expose ``stop()`` so :func:`run_app`'s cleanup
    block doesn't branch on which mode is active.
    """

    def stop(self) -> None: ...  # pragma: no cover - interface only


class _SubprocessServer(_ServerHandle):
    def __init__(self, proc: subprocess.Popen) -> None:
        self.proc = proc

    def stop(self) -> None:
        _terminate_subprocess(self.proc)


class _ThreadedServer(_ServerHandle):
    """Uvicorn running on a background thread inside this process.

    Used when frozen so we don't re-launch the PyInstaller bundle as
    a subprocess (slow on onefile, redundant on onedir). Stop is a
    polite ``server.should_exit = True`` followed by a wait.
    """

    def __init__(self, server: Any, thread: threading.Thread) -> None:
        self.server = server
        self.thread = thread

    def stop(self) -> None:
        try:
            self.server.should_exit = True
        except AttributeError:
            pass
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            _log.warning("uvicorn thread did not exit within 5s")


def _start_threaded_uvicorn(host: str, port: int) -> _ThreadedServer:
    """Run ``care.main:create_app`` in a uvicorn thread.

    Imported lazily because frozen builds may not have uvicorn on
    the import path until pythonnet/pywebview have been initialised
    in some edge cases.
    """
    import uvicorn

    config = uvicorn.Config(
        "care.main:create_app",
        factory=True,
        host=host,
        port=port,
        log_level="info",
        # Disable signal handlers — the parent (pywebview) already
        # owns SIGINT/SIGTERM. We stop via should_exit instead.
        lifespan="on",
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[assignment]
    thread = threading.Thread(
        target=server.run,
        name="uvicorn-frozen",
        daemon=True,
    )
    thread.start()
    return _ThreadedServer(server, thread)


def run_app(
    *,
    config: AppConfig,
    config_path: Optional[Path],
    host: str = "127.0.0.1",
    port: int = 7860,
    title: str = DEFAULT_TITLE,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    server_ready_timeout_s: float = 15.0,
    use_inprocess_server: Optional[bool] = None,
) -> int:
    """Start the server, open a pywebview window, clean up on close.

    ``use_inprocess_server`` selects the strategy:
    - ``None`` (default) → subprocess in dev, threaded when frozen.
    - ``True`` → always threaded (frozen-style).
    - ``False`` → always subprocess (dev-style).

    Returns:
    - 0 on clean window close.
    - 2 if the loopback / port checks fail before any server starts.
    - 3 if the server didn't become ready within the timeout.
    - 4 if pywebview can't initialise (missing platform deps).
    """
    if host not in LOOPBACK_HOSTS:
        _log.error(
            "refusing non-loopback host %r — desktop app must use loopback",
            host,
        )
        return 2

    actual_port = find_free_port(port, host)
    base_url = f"http://{host}:{actual_port}/"

    try:
        import webview  # type: ignore[import-not-found]
    except ImportError as exc:
        _log.error(
            "pywebview is not installed in this environment "
            "(%s). Install with `uv sync` or pip install pywebview.",
            exc,
        )
        return 4

    user_data_dir = _resolve_user_data_dir(config)

    if use_inprocess_server is None:
        from ..core.runtime_paths import is_frozen

        use_inprocess_server = is_frozen()

    server_handle: _ServerHandle
    if use_inprocess_server:
        _log.info("starting in-process uvicorn on %s", base_url)
        server_handle = _start_threaded_uvicorn(host, actual_port)
    else:
        argv = _build_serve_argv(
            host=host, port=actual_port, config_path=config_path
        )
        _log.info("launching server subprocess on %s", base_url)
        server_handle = _SubprocessServer(subprocess.Popen(argv))

    try:
        if not wait_for_server(base_url, timeout_s=server_ready_timeout_s):
            _log.error("server did not become ready at %s within timeout", base_url)
            return 3

        # Set the AppUserModelID BEFORE the first window so the
        # taskbar associates our windows with CARE from the start.
        _set_windows_app_user_model_id()

        ico_path, png_path = _resolve_app_icon_paths()

        window = webview.create_window(
            title,
            base_url,
            width=width,
            height=height,
            resizable=True,
        )

        # On Windows, drive the title-bar icon via Win32 once the
        # window is shown (FindWindow needs the HWND to exist).
        # ``window.events.shown`` fires after the OS paints the
        # window. Wrap in try/except so a pywebview API change can't
        # crash the app.
        if ico_path is not None and sys.platform == "win32" and window is not None:
            try:
                window.events.shown += lambda: _attach_windows_icon(title, ico_path)
            except AttributeError:  # pragma: no cover
                _log.debug("pywebview Window has no events.shown; skipping icon hook")

        # pywebview calls this ``storage_path``; ``private_mode=False``
        # is required for the path to actually persist anything (the
        # default is private/incognito which throws cookies + cache
        # away on close).
        #
        # ``icon=`` is consumed by the chosen GUI backend:
        #   - GTK / Qt: accept a PNG and use it for the window icon.
        #   - WinForms (pywebview >=5 on Windows): feed the path to
        #     ``System.Drawing.Icon(path)``, which only accepts ``.ico``
        #     files. Passing a PNG raises ArgumentException on the
        #     GUI thread and crashes the app. We drive the Windows
        #     icon ourselves via ``WM_SETICON`` in
        #     ``_attach_windows_icon``, so on Windows we skip ``icon=``
        #     entirely.
        start_kwargs: dict[str, Any] = {
            "storage_path": str(user_data_dir),
            "private_mode": False,
        }
        if png_path is not None and sys.platform != "win32":
            start_kwargs["icon"] = str(png_path)

        # On Windows, prime pythonnet so pywebview's winforms backend
        # can ``import clr`` successfully. On other platforms this is
        # a no-op.
        if not _bootstrap_pythonnet_for_winforms():
            return 4

        webview.start(**start_kwargs)
        return 0
    finally:
        server_handle.stop()


def _terminate_subprocess(proc: subprocess.Popen) -> None:
    """Graceful terminate → wait 5s → kill if still alive."""
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _log.warning("server subprocess did not exit after terminate(); killing")
        proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _log.error("server subprocess refused to die")
