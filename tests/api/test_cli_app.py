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
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as held:
        held.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        held.bind(("127.0.0.1", 0))
        held.listen(1)
        held_port = held.getsockname()[1]
        actual = desktop.find_free_port(held_port)
        assert actual != held_port


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


class _FakeWebview:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.start_kwargs: dict[str, Any] = {}

    def create_window(self, title: str, url: str, **kwargs: Any) -> None:
        self.created.append({"title": title, "url": url, **kwargs})

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
