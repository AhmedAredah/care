"""Desktop-app subcommand wiring (Phase 14.1).

Pywebview and uvicorn boundaries are mocked; we never open a real
window or spawn a real server here. Goal: prove that ``cmd_app`` /
``run_app`` build the right argv, open a window pointed at the
right URL, and clean up the subprocess on close.
"""
from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from care.cli import desktop
from care.core.config import AppConfig

# ----- find_free_port --------------------------------------------------


def test_find_free_port_returns_preferred_when_free() -> None:
    # 0 == OS-assigned, never collides; treat 0 as the preferred port.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # Port now released; should be available again.
    assert desktop.find_free_port(port) == port


def test_find_free_port_falls_back_when_taken() -> None:
    # Hold a port open; ``find_free_port`` must return a different one.
    # Don't set SO_REUSEADDR — we want this socket to behave like a
    # normal listener that takes the port exclusively. (On Windows,
    # SO_REUSEADDR allows a second socket to bind the same port if it
    # also sets the option, which would defeat the test.)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        held_port = held.getsockname()[1]
        actual = desktop.find_free_port(held_port)
        assert actual != held_port


# ----- loopback enforcement at the bind site ---------------------------
#
# ``run_app`` already rejects non-loopback hosts at the outer boundary,
# but the inner port helpers also assert it themselves so the constraint
# is local to every ``socket.bind`` call site. This makes the
# loopback-only guarantee visible to static analysis (CodeQL
# ``py/bind-socket-all-network-interfaces``) without it having to trace
# the call graph through ``run_app``.


def test_find_free_port_refuses_non_loopback() -> None:
    import pytest

    with pytest.raises(ValueError, match="non-loopback"):
        desktop.find_free_port(7860, host="0.0.0.0")


def test_is_port_free_refuses_non_loopback() -> None:
    import pytest

    with pytest.raises(ValueError, match="non-loopback"):
        desktop._is_port_free("0.0.0.0", 7860)


def test_assert_loopback_accepts_every_loopback_alias() -> None:
    # All three loopback hosts must pass without raising. We test the
    # assertion helper directly so the test does not depend on whether
    # ``::1`` actually has a working interface on the test runner
    # (it doesn't on every CI machine).
    for host in ("127.0.0.1", "localhost", "::1"):
        desktop._assert_loopback(host)  # must not raise


def test_assert_loopback_rejects_wildcards_and_remote_hosts() -> None:
    import pytest

    for host in ("0.0.0.0", "::", "192.168.1.1", "example.com"):
        with pytest.raises(ValueError, match="non-loopback"):
            desktop._assert_loopback(host)


# ----- _build_serve_argv ----------------------------------------------


def test_build_serve_argv_includes_config_when_given() -> None:
    cfg_path = Path("/tmp/example.yaml")
    argv = desktop._build_serve_argv(host="127.0.0.1", port=7860, config_path=cfg_path)
    assert argv[0] == sys.executable
    assert "serve" in argv
    assert "--host" in argv and "127.0.0.1" in argv
    assert "--port" in argv and "7860" in argv
    assert "--config" in argv and str(cfg_path) in argv


def test_build_serve_argv_omits_config_when_none() -> None:
    argv = desktop._build_serve_argv(host="127.0.0.1", port=7860, config_path=None)
    assert "--config" not in argv


# ----- run_app guards --------------------------------------------------


def test_run_app_rejects_non_loopback_host() -> None:
    rc = desktop.run_app(
        config=AppConfig(),
        config_path=None,
        host="0.0.0.0",  # non-loopback
        port=7860,
    )
    assert rc == 2  # policy guard


# ----- run_app happy path (mocked) -------------------------------------


class _FakeProc:
    def __init__(self) -> None:
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return 0 if self.terminated else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        self.killed = True


class _FakeWindowEvents:
    """Mimics pywebview's ``window.events.shown += handler`` API."""
    def __init__(self) -> None:
        self.shown_handlers: list = []

    @property
    def shown(self):  # noqa: D401 — fake property to mirror pywebview
        return self

    def __iadd__(self, handler):
        self.shown_handlers.append(handler)
        return self


class _FakeWindow:
    def __init__(self, title: str) -> None:
        self.title = title
        self.events = _FakeWindowEvents()


class _FakeWebview:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.start_kwargs: dict[str, Any] = {}
        self.last_window: _FakeWindow | None = None

    def create_window(self, title: str, url: str, **kwargs: Any):
        self.created.append({"title": title, "url": url, **kwargs})
        win = _FakeWindow(title)
        self.last_window = win
        return win

    def start(self, **kwargs: Any) -> None:
        self.start_kwargs = kwargs


def test_run_app_opens_window_at_loopback_url(monkeypatch, tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")

    fake_proc = _FakeProc()
    fake_webview = _FakeWebview()

    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(desktop, "wait_for_server", lambda *a, **kw: True)

    # pywebview is imported inside run_app via ``import webview``.
    # Patch the sys.modules entry so the function-local import binds to
    # our fake without forcing a real pywebview install on CI.
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    rc = desktop.run_app(
        config=cfg,
        config_path=None,
        host="127.0.0.1",
        port=7860,
    )

    assert rc == 0
    assert len(fake_webview.created) == 1
    window = fake_webview.created[0]
    assert window["url"].startswith("http://127.0.0.1:")
    assert window["title"] == desktop.DEFAULT_TITLE
    assert window["width"] == desktop.DEFAULT_WIDTH
    assert window["height"] == desktop.DEFAULT_HEIGHT
    # Cache lives inside our managed work_dir. pywebview's kwarg is
    # ``storage_path``; ``private_mode=False`` is required for the
    # path to actually persist anything across launches.
    assert "storage_path" in fake_webview.start_kwargs
    assert str(tmp_path / "work") in fake_webview.start_kwargs["storage_path"]
    assert fake_webview.start_kwargs.get("private_mode") is False
    # Subprocess was terminated on window close.
    assert fake_proc.terminated is True


def test_run_app_returns_3_when_server_never_ready(
    monkeypatch, tmp_path: Path
) -> None:
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    fake_proc = _FakeProc()
    fake_webview = _FakeWebview()

    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(desktop, "wait_for_server", lambda *a, **kw: False)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    rc = desktop.run_app(
        config=cfg,
        config_path=None,
        host="127.0.0.1",
        port=7860,
    )
    assert rc == 3
    # No window opened.
    assert fake_webview.created == []
    # Subprocess still terminated.
    assert fake_proc.terminated is True


def test_run_app_returns_4_when_pywebview_missing(
    monkeypatch, tmp_path: Path
) -> None:
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")

    real_import = __builtins__["__import__"] if isinstance(
        __builtins__, dict
    ) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "webview":
            raise ImportError("simulated missing pywebview")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    rc = desktop.run_app(
        config=cfg,
        config_path=None,
        host="127.0.0.1",
        port=7860,
    )
    assert rc == 4


# ----- subprocess cleanup -----------------------------------------------


def test_terminate_subprocess_kills_after_grace_period(monkeypatch) -> None:
    """If terminate() doesn't bring the child down in 5s, kill() runs."""

    class _Stubborn:
        def __init__(self) -> None:
            self.alive = True
            self.terminated = False
            self.killed = False
            self._wait_calls = 0

        def poll(self):
            return None if self.alive else 0

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True
            self.alive = False

        def wait(self, timeout=None):
            self._wait_calls += 1
            if self._wait_calls == 1:
                raise subprocess.TimeoutExpired(cmd="serve", timeout=timeout)
            return 0

    proc = _Stubborn()
    desktop._terminate_subprocess(proc)
    assert proc.terminated is True
    assert proc.killed is True


# ----- cmd_app dispatch ------------------------------------------------


def test_app_subcommand_has_no_non_loopback_escape_hatch() -> None:
    """The app command must not accept --allow-non-loopback. The
    only loopback safety knob lives on `serve`; the desktop wrapper
    is locked tighter."""
    from care.cli.main import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([
            "app", "--allow-non-loopback", "--host", "0.0.0.0",
        ])


def test_cmd_app_passes_args_through(monkeypatch) -> None:
    """The CLI hook should call run_app with the resolved config."""
    from care.cli.main import cmd_app

    captured: dict[str, Any] = {}

    def fake_run_app(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr("care.cli.desktop.run_app", fake_run_app)

    args = SimpleNamespace(
        config=None,
        host="127.0.0.1",
        port=7861,
        title="Test Title",
        width=1024,
        height=768,
    )
    rc = cmd_app(args)
    assert rc == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 7861
    assert captured["title"] == "Test Title"
    assert captured["width"] == 1024
    assert captured["height"] == 768


# ----- icon plumbing ---------------------------------------------------


def test_resolve_app_icon_paths_finds_assets() -> None:
    """The bundled assets/icon.{ico,png} are present in the repo, so
    in dev mode the resolver should find both."""
    ico, png = desktop._resolve_app_icon_paths()
    assert ico is not None and ico.suffix == ".ico"
    assert png is not None and png.suffix == ".png"
    assert ico.exists()
    assert png.exists()


def test_set_windows_app_user_model_id_no_op_off_windows(monkeypatch) -> None:
    """Outside Windows the helper must be a quiet no-op (no shell32
    import attempt). Test by forcing a non-Windows platform string."""
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    # Should return without raising — nothing else to assert because
    # the helper has no externally observable effect off Windows.
    desktop._set_windows_app_user_model_id("test.id")


def test_attach_windows_icon_no_op_off_windows(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    fake_ico = tmp_path / "fake.ico"
    fake_ico.write_bytes(b"")
    desktop._attach_windows_icon("CARE", fake_ico)


def test_run_app_passes_png_icon_to_webview_start(
    monkeypatch, tmp_path: Path
) -> None:
    """Off-Windows, run_app must pass the bundled assets/icon.png as
    ``icon=`` to ``webview.start`` so GTK/Qt picks it up."""
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")

    fake_proc = _FakeProc()
    fake_webview = _FakeWebview()

    monkeypatch.setattr(desktop.sys, "platform", "linux")
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(desktop, "wait_for_server", lambda *a, **kw: True)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)

    rc = desktop.run_app(
        config=cfg, config_path=None, host="127.0.0.1", port=7860,
    )
    assert rc == 0
    icon_kw = fake_webview.start_kwargs.get("icon")
    # The bundled assets/icon.png in the repo provides this; if the
    # repo dropped it the test surfaces it.
    assert icon_kw is not None
    assert icon_kw.endswith("icon.png")


def test_run_app_does_not_pass_icon_to_webview_start_on_windows(
    monkeypatch, tmp_path: Path
) -> None:
    """On Windows, ``webview.start(icon=...)`` reaches pywebview's
    WinForms backend, which feeds the path to ``System.Drawing.Icon``.
    That .NET class only accepts ``.ico`` files; a PNG raises
    ArgumentException on the GUI thread and crashes the app. The
    Windows icon is set out-of-band via ``WM_SETICON`` in
    ``_attach_windows_icon`` instead, so on Windows we must omit
    ``icon=`` entirely."""
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")

    fake_proc = _FakeProc()
    fake_webview = _FakeWebview()

    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(desktop, "wait_for_server", lambda *a, **kw: True)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    # Block the real Windows-only helpers from doing anything ctypes-y
    # or .NET-y on a Linux test runner.
    monkeypatch.setattr(desktop, "_attach_windows_icon", lambda *a, **kw: None)
    monkeypatch.setattr(desktop, "_set_windows_app_user_model_id", lambda *a, **kw: None)
    monkeypatch.setattr(desktop, "_bootstrap_pythonnet_for_winforms", lambda: True)

    rc = desktop.run_app(
        config=cfg, config_path=None, host="127.0.0.1", port=7860,
    )
    assert rc == 0
    assert "icon" not in fake_webview.start_kwargs


def test_run_app_registers_windows_icon_hook(monkeypatch, tmp_path: Path) -> None:
    """On Windows, run_app must register a shown-event handler so the
    title-bar icon is set after the window paints. We force-pretend
    we're on Windows for this test."""
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")

    fake_proc = _FakeProc()
    fake_webview = _FakeWebview()

    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(desktop, "wait_for_server", lambda *a, **kw: True)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    # Block the actual ctypes / .NET calls from running by stubbing
    # the helpers that own them.
    monkeypatch.setattr(desktop, "_attach_windows_icon", lambda *a, **kw: None)
    monkeypatch.setattr(desktop, "_set_windows_app_user_model_id", lambda *a, **kw: None)
    monkeypatch.setattr(desktop, "_bootstrap_pythonnet_for_winforms", lambda: True)

    rc = desktop.run_app(
        config=cfg, config_path=None, host="127.0.0.1", port=7860,
    )
    assert rc == 0
    win = fake_webview.last_window
    assert win is not None
    # One shown-handler was registered (the icon-attach lambda).
    assert len(win.events.shown_handlers) == 1


def test_run_app_bootstraps_pythonnet_on_windows(
    monkeypatch, tmp_path: Path
) -> None:
    """On Windows, run_app must call ``pythonnet.load()`` before
    ``webview.start()`` — otherwise pywebview's WinForms backend does
    ``import clr`` and crashes with ``ModuleNotFoundError`` because
    pythonnet 3.x's ``clr`` meta-loader has not been registered yet.

    The bootstrap must run AFTER ``webview.create_window`` (so the
    pywebview module is imported) but BEFORE ``webview.start()``."""
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")

    fake_proc = _FakeProc()
    fake_webview = _FakeWebview()

    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(desktop, "wait_for_server", lambda *a, **kw: True)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop, "_attach_windows_icon", lambda *a, **kw: None)
    monkeypatch.setattr(desktop, "_set_windows_app_user_model_id", lambda *a, **kw: None)

    calls: list[str] = []

    def fake_bootstrap() -> bool:
        calls.append("bootstrap")
        return True

    original_start = fake_webview.start

    def fake_start(**kwargs):
        calls.append("start")
        return original_start(**kwargs)

    monkeypatch.setattr(desktop, "_bootstrap_pythonnet_for_winforms", fake_bootstrap)
    monkeypatch.setattr(fake_webview, "start", fake_start)

    rc = desktop.run_app(
        config=cfg, config_path=None, host="127.0.0.1", port=7860,
    )
    assert rc == 0
    # Bootstrap ran before webview.start.
    assert calls == ["bootstrap", "start"]


def test_run_app_returns_4_when_pythonnet_bootstrap_fails(
    monkeypatch, tmp_path: Path
) -> None:
    """A failed ``pythonnet.load()`` (e.g., no .NET runtime installed)
    must return exit code 4 instead of crashing inside pywebview. The
    GUI cannot start without the runtime; surfacing exit code 4 lets
    the CLI/installer present a clear remediation."""
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")

    fake_proc = _FakeProc()
    fake_webview = _FakeWebview()

    monkeypatch.setattr(desktop.sys, "platform", "win32")
    monkeypatch.setattr(desktop.subprocess, "Popen", lambda *a, **kw: fake_proc)
    monkeypatch.setattr(desktop, "wait_for_server", lambda *a, **kw: True)
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr(desktop, "_attach_windows_icon", lambda *a, **kw: None)
    monkeypatch.setattr(desktop, "_set_windows_app_user_model_id", lambda *a, **kw: None)
    monkeypatch.setattr(desktop, "_bootstrap_pythonnet_for_winforms", lambda: False)

    rc = desktop.run_app(
        config=cfg, config_path=None, host="127.0.0.1", port=7860,
    )
    assert rc == 4
    # webview.start must not have been called when bootstrap fails.
    assert fake_webview.start_kwargs == {}


def test_bootstrap_pythonnet_is_noop_on_non_windows(monkeypatch) -> None:
    """The bootstrap is a no-op on Linux/macOS — those pywebview
    backends (GTK/Qt, Cocoa) don't go through clr. We verify by
    swapping ``sys.platform`` and asserting the helper returns True
    without trying to import pythonnet."""
    monkeypatch.setattr(desktop.sys, "platform", "linux")
    # Even if pythonnet were missing entirely, this must succeed.
    monkeypatch.setitem(sys.modules, "pythonnet", None)
    assert desktop._bootstrap_pythonnet_for_winforms() is True
