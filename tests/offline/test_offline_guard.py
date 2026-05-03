"""Offline guard tests.

Covers `test_offline_mode_blocks_huggingface_downloads` semantics by
asserting that any non-loopback `socket.connect` raises while the guard
is active and that the Hugging Face / Transformers offline env vars
are set.
"""
from __future__ import annotations

import os
import socket

import pytest

from care.core import offline_guard
from care.core.constants import HF_OFFLINE_ENV
from care.core.errors import OfflineGuardError


@pytest.fixture(autouse=True)
def _reset_guard():
    was_enabled = offline_guard.is_enabled()
    yield
    if offline_guard.is_enabled() and not was_enabled:
        offline_guard.disable()
    elif not offline_guard.is_enabled() and was_enabled:
        offline_guard.enable()


def test_offline_guard_blocks_external_tcp_connect() -> None:
    offline_guard.enable()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(OfflineGuardError):
                s.connect(("93.184.216.34", 80))  # example.com IP literal
        finally:
            s.close()
    finally:
        offline_guard.disable()


def test_offline_guard_blocks_external_create_connection() -> None:
    offline_guard.enable()
    try:
        with pytest.raises(OfflineGuardError):
            socket.create_connection(("huggingface.co", 443), timeout=0.1)
    finally:
        offline_guard.disable()


def test_offline_guard_allows_loopback_create_connection() -> None:
    """Loopback must remain reachable so the local FastAPI server keeps working."""
    offline_guard.enable()
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    try:
        client = socket.create_connection(("127.0.0.1", port), timeout=1)
        client.close()
    finally:
        listener.close()
        offline_guard.disable()


def test_offline_mode_sets_huggingface_env_vars() -> None:
    """Equivalent to test_offline_mode_blocks_huggingface_downloads:
    when offline mode is enabled, the env vars Transformers/HF Hub honor
    must be set.
    """
    offline_guard.enable()
    try:
        for key, expected in HF_OFFLINE_ENV.items():
            assert os.environ.get(key) == expected, f"{key} not set to {expected}"
    finally:
        offline_guard.disable()


def test_offline_guard_is_idempotent() -> None:
    offline_guard.enable()
    try:
        offline_guard.enable()
        assert offline_guard.is_enabled() is True
    finally:
        offline_guard.disable()
        offline_guard.disable()
        assert offline_guard.is_enabled() is False
