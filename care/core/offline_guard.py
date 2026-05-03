"""Strict offline guard.

When enabled, monkey-patches `socket.socket.connect` so any attempt to
reach a non-loopback address raises `OfflineGuardError`. Also sets the
Hugging Face / Transformers offline environment variables.

claude/rules/offline-security.md`.
"""
from __future__ import annotations

import logging
import os
import socket
from typing import Any

from .constants import HF_OFFLINE_ENV
from .errors import OfflineGuardError

_log = logging.getLogger(__name__)

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

_original_connect = None
_original_create_connection = None
_enabled = False


def _is_loopback(address: Any) -> bool:
    if isinstance(address, tuple) and address:
        host = address[0]
        if isinstance(host, (bytes, bytearray)):
            host = host.decode("ascii", errors="ignore")
        if not isinstance(host, str):
            return False
        if host in _LOOPBACK_HOSTS:
            return True
        if host.startswith("127.") or host.startswith("::ffff:127."):
            return True
        return False
    if isinstance(address, str):
        # Unix domain sockets are filesystem paths; allow.
        return True
    return False


def _guarded_connect(self: socket.socket, address, *args, **kwargs):
    if not _is_loopback(address):
        raise OfflineGuardError(
            f"Offline mode blocked external socket connect: {address!r}"
        )
    return _original_connect(self, address, *args, **kwargs)


def _guarded_create_connection(address, *args, **kwargs):
    if not _is_loopback(address):
        raise OfflineGuardError(
            f"Offline mode blocked socket.create_connection: {address!r}"
        )
    return _original_create_connection(address, *args, **kwargs)


def enable() -> None:
    """Activate the guard. Idempotent."""
    global _original_connect, _original_create_connection, _enabled
    if _enabled:
        return
    for key, value in HF_OFFLINE_ENV.items():
        os.environ.setdefault(key, value)
    _original_connect = socket.socket.connect
    _original_create_connection = socket.create_connection
    socket.socket.connect = _guarded_connect  # type: ignore[assignment]
    socket.create_connection = _guarded_create_connection  # type: ignore[assignment]
    _enabled = True
    _log.info("offline_guard enabled")


def disable() -> None:
    """Deactivate the guard. Test-only."""
    global _original_connect, _original_create_connection, _enabled
    if not _enabled:
        return
    socket.socket.connect = _original_connect  # type: ignore[assignment]
    socket.create_connection = _original_create_connection  # type: ignore[assignment]
    _original_connect = None
    _original_create_connection = None
    _enabled = False
    _log.info("offline_guard disabled")


def is_enabled() -> bool:
    return _enabled
