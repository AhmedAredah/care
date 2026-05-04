"""`serve` CLI must bind to 127.0.0.1 by default."""
from __future__ import annotations

import argparse

from care.cli.main import build_parser, cmd_serve


def test_serve_default_host_is_loopback(monkeypatch) -> None:
    """When --host is not specified, cmd_serve must use 127.0.0.1 from the
    default config and never expose the API to the network."""
    captured: dict[str, object] = {}

    def fake_uvicorn_run(app, **kwargs):  # noqa: ARG001
        captured["app"] = app
        captured.update(kwargs)

    class FakeUvicorn:
        run = staticmethod(fake_uvicorn_run)

    import sys

    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn)

    args = argparse.Namespace(
        config=None, host=None, port=None, allow_non_loopback=False
    )
    rc = cmd_serve(args)
    assert rc == 0
    assert captured["host"] == "127.0.0.1"
    assert captured["app"] == "care.main:create_app"
    assert captured["factory"] is True


def test_serve_refuses_non_loopback_without_override(capsys) -> None:
    args = argparse.Namespace(
        config=None,
        host="0.0.0.0",
        port=None,
        allow_non_loopback=False,
    )
    rc = cmd_serve(args)
    assert rc == 2
    err = capsys.readouterr().err
    assert "non-loopback" in err


def test_serve_help_lists_host_and_port_flags() -> None:
    parser = build_parser()
    serve_parser = None
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            serve_parser = action.choices.get("serve")
            break
    assert serve_parser is not None
    help_text = serve_parser.format_help()
    assert "--host" in help_text
    assert "--port" in help_text
    assert "--allow-non-loopback" in help_text
