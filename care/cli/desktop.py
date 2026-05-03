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


def find_free_port(preferred: int, host: str = "127.0.0.1") -> int:
    """Return ``preferred`` if it's free, otherwise an OS-assigned port.

    Tested with ``SO_REUSEADDR`` to avoid TIME_WAIT pollution between
    quick relaunches of the desktop app.
    """
    if _is_port_free(host, preferred):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _is_port_free(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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

        webview.create_window(
            title,
            base_url,
            width=width,
            height=height,
            resizable=True,
        )
        # pywebview calls this ``storage_path``; ``private_mode=False``
        # is required for the path to actually persist anything (the
        # default is private/incognito which throws cookies + cache
        # away on close).
        webview.start(storage_path=str(user_data_dir), private_mode=False)
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
