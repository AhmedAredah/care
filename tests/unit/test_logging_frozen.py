"""Rotating-file logging for frozen builds (Phase 15.4)."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from care.core import logging as oce_logging


@pytest.fixture(autouse=True)
def _reset_root_logger():
    """Strip all handlers between tests so each starts clean."""
    root = logging.getLogger()
    saved = list(root.handlers)
    for h in list(root.handlers):
        root.removeHandler(h)
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in saved:
        root.addHandler(h)


def _redirect_user_data(monkeypatch, tmp_path: Path) -> Path:
    """Force runtime_paths.logs_dir to tmp_path."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


def test_configure_logging_for_frozen_creates_log_file(
    monkeypatch, tmp_path: Path
) -> None:
    _redirect_user_data(monkeypatch, tmp_path)
    oce_logging.configure_logging_for_frozen()
    logging.getLogger().error("hello-from-test")
    # Find the log file under whichever subdir resolved.
    candidates = list(tmp_path.rglob("care.log"))
    assert len(candidates) == 1
    body = candidates[0].read_text(encoding="utf-8")
    assert "hello-from-test" in body


def test_configure_logging_for_frozen_attaches_rotating_handler(
    monkeypatch, tmp_path: Path
) -> None:
    from logging.handlers import RotatingFileHandler

    _redirect_user_data(monkeypatch, tmp_path)
    oce_logging.configure_logging_for_frozen(max_bytes=1024, backup_count=2)
    handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, RotatingFileHandler)
    ]
    assert len(handlers) == 1
    assert handlers[0].maxBytes == 1024
    assert handlers[0].backupCount == 2


def test_configure_logging_for_frozen_is_idempotent(
    monkeypatch, tmp_path: Path
) -> None:
    from logging.handlers import RotatingFileHandler

    _redirect_user_data(monkeypatch, tmp_path)
    oce_logging.configure_logging_for_frozen()
    oce_logging.configure_logging_for_frozen()
    handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, RotatingFileHandler)
    ]
    assert len(handlers) == 1


def test_pii_filter_applied_to_file_handler(
    monkeypatch, tmp_path: Path
) -> None:
    """A log line containing an email must be redacted before it
    reaches the file handler."""
    _redirect_user_data(monkeypatch, tmp_path)
    oce_logging.configure_logging_for_frozen()
    logging.getLogger().info("operator email is alice@example.com")
    candidates = list(tmp_path.rglob("care.log"))
    body = candidates[0].read_text(encoding="utf-8")
    assert "alice@example.com" not in body
    assert "[EMAIL]" in body
