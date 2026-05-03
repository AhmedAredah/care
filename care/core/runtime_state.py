"""Live-process state that the GUI surfaces (Phase 13.7).

A small module-level snapshot of the values the server was actually
booted with — host, port, expose_to_network. Compared against the
on-disk config to tell the operator when a Settings save needs a
server restart to take effect.

The CLI's ``serve`` subcommand writes to this snapshot just before
calling ``uvicorn.run``; the route handlers read from it. Anything
else (tests, ad-hoc imports) sees ``boot_snapshot=None`` and the
restart-required endpoint reports "unknown" rather than guessing.
"""
from __future__ import annotations

import threading
from typing import Any, Optional

# Paths whose changes always require a server restart to take effect.
# host / port are baked into uvicorn at boot. ``expose_to_network``
# is policy-only today but the cli's bind check reads it at startup,
# so a runtime flip would be misleading without a restart.
RESTART_REQUIRED_PATHS: tuple[str, ...] = (
    "server.host",
    "server.port",
    "server.expose_to_network",
)

_LOCK = threading.RLock()
_BOOT_SNAPSHOT: Optional[dict[str, Any]] = None


def set_boot_snapshot(*, host: str, port: int, expose_to_network: bool) -> None:
    """Capture the values uvicorn is about to bind with."""
    global _BOOT_SNAPSHOT
    with _LOCK:
        _BOOT_SNAPSHOT = {
            "server.host": str(host),
            "server.port": int(port),
            "server.expose_to_network": bool(expose_to_network),
        }


def get_boot_snapshot() -> Optional[dict[str, Any]]:
    """Return a copy of the snapshot, or ``None`` if never set."""
    with _LOCK:
        if _BOOT_SNAPSHOT is None:
            return None
        return dict(_BOOT_SNAPSHOT)


def clear_boot_snapshot() -> None:
    """Used by tests to reset between cases."""
    global _BOOT_SNAPSHOT
    with _LOCK:
        _BOOT_SNAPSHOT = None
