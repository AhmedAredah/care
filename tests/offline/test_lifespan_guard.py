"""FastAPI lifespan must activate the runtime offline guard.

Without this hook, ``offline.enabled = true`` in config.yaml is just
a setting nobody checks: outbound socket connects from any plugin or
HTTP client running inside the FastAPI process would still go
through, and the GUI's offline status indicator (which reads the
guard's runtime flag) would correctly report "Network access enabled"
— in other words, the contract's offline-first guarantee would not
be enforced at runtime.
"""
from __future__ import annotations

import asyncio

import pytest

from care.core import offline_guard
from care.core.config import AppConfig
from care.main import create_app


@pytest.fixture(autouse=True)
def _reset_guard():
    """Restore the global guard state after each test."""
    was_enabled = offline_guard.is_enabled()
    yield
    if offline_guard.is_enabled() and not was_enabled:
        offline_guard.disable()
    elif not offline_guard.is_enabled() and was_enabled:
        offline_guard.enable()


def _run_lifespan(app) -> None:
    """Drive the app through one lifespan startup cycle."""

    async def go():
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(go())


def test_lifespan_activates_offline_guard_when_config_enabled() -> None:
    offline_guard.disable()
    assert offline_guard.is_enabled() is False

    cfg = AppConfig()
    assert cfg.offline.enabled is True

    app = create_app()

    # The lifespan reads config via the same loader the deps use.
    # By default that returns AppConfig() with offline.enabled=True.
    _run_lifespan(app)

    assert offline_guard.is_enabled() is True, (
        "FastAPI lifespan must call offline_guard.enable() when "
        "offline.enabled=true in config — otherwise the GUI's offline "
        "status badge correctly shows 'Network access enabled'."
    )


def test_lifespan_does_not_activate_guard_when_config_disabled(monkeypatch) -> None:
    """When the operator explicitly turns offline mode off, lifespan
    must NOT silently re-enable the guard. The contract says offline-
    first BY DEFAULT, but a deliberately overridden config is a
    deliberate choice we honour (with a logged warning).

    The lifespan calls ``get_app_config`` directly (not via FastAPI's
    DI) so we monkey-patch the symbol on the ``care.main`` module
    where the lifespan imported it."""
    offline_guard.disable()

    cfg = AppConfig()
    cfg.offline.enabled = False

    import care.main

    monkeypatch.setattr(care.main, "get_app_config", lambda: cfg)

    app = create_app()
    _run_lifespan(app)

    assert offline_guard.is_enabled() is False
