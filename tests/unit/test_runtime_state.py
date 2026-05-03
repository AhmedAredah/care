"""Boot-snapshot module (Phase 13.7)."""
from __future__ import annotations

import pytest

from care.core.runtime_state import (
    RESTART_REQUIRED_PATHS,
    clear_boot_snapshot,
    get_boot_snapshot,
    set_boot_snapshot,
)


@pytest.fixture(autouse=True)
def _clean_snapshot():
    clear_boot_snapshot()
    yield
    clear_boot_snapshot()


def test_get_boot_snapshot_returns_none_initially() -> None:
    assert get_boot_snapshot() is None


def test_set_and_get_boot_snapshot_round_trip() -> None:
    set_boot_snapshot(host="127.0.0.1", port=7860, expose_to_network=False)
    snap = get_boot_snapshot()
    assert snap == {
        "server.host": "127.0.0.1",
        "server.port": 7860,
        "server.expose_to_network": False,
    }


def test_get_boot_snapshot_returns_a_copy() -> None:
    set_boot_snapshot(host="127.0.0.1", port=7860, expose_to_network=False)
    snap = get_boot_snapshot()
    snap["server.port"] = 9999
    again = get_boot_snapshot()
    assert again["server.port"] == 7860


def test_restart_required_paths_includes_host_port_expose() -> None:
    assert "server.host" in RESTART_REQUIRED_PATHS
    assert "server.port" in RESTART_REQUIRED_PATHS
    assert "server.expose_to_network" in RESTART_REQUIRED_PATHS
