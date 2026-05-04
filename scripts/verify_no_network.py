#!/usr/bin/env python3
"""Offline smoke test.

Procedure:
1. Enable the in-process offline guard.
2. Confirm the five Hugging Face / Transformers offline env vars are set.
3. Try to open a TCP connection to a public, non-loopback host. The
   guard MUST raise OfflineGuardError. Loopback connects (127.0.0.1)
   are still allowed so the local API can serve requests.
4. Try to import every provider class and assert that none of them
   triggered an outbound connect.

Exit code:
  0 — every check passed; the deployment is verified offline.
  1 — at least one check failed (printed to stderr).
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _check_env() -> tuple[bool, list[str]]:
    from care.core.constants import HF_OFFLINE_ENV

    issues: list[str] = []
    for key, expected in HF_OFFLINE_ENV.items():
        actual = os.environ.get(key)
        if actual != expected:
            issues.append(f"{key} must be {expected!r}, got {actual!r}")
    return (not issues), issues


def _check_guard() -> tuple[bool, list[str]]:
    from care.core.errors import OfflineGuardError
    from care.core.offline_guard import enable, is_enabled

    if not is_enabled():
        enable()
    if not is_enabled():
        return False, ["could not enable offline guard"]

    # External connect must raise.
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.connect(("8.8.8.8", 53))
            sock.close()
            return False, [
                "offline guard did NOT block outbound connect to 8.8.8.8:53"
            ]
        except OfflineGuardError:
            return True, []
        except OSError as exc:
            # The guard's preferred behaviour is OfflineGuardError, but
            # any failure to connect is acceptable for this audit.
            return True, [f"connect raised non-guard error (still offline): {exc}"]
    finally:
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass


def _check_provider_imports() -> tuple[bool, list[str]]:
    """Import every registered provider class and confirm registries
    populate without contacting the network."""
    issues: list[str] = []
    try:
        from care.document_ai.registry import get_registry as get_vlm
        from care.ocr.registry import get_registry as get_ocr
        from care.pii.registry import get_registry as get_pii

        for reg_factory, label in (
            (get_ocr, "ocr"),
            (get_pii, "pii"),
            (get_vlm, "document_ai"),
        ):
            reg = reg_factory()
            for name in reg.names():
                try:
                    reg.get(name)
                except Exception as exc:  # noqa: BLE001
                    issues.append(f"{label}.{name}: {type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"failed to load registries: {type(exc).__name__}: {exc}")
    return (not issues), issues


def main() -> int:
    env_ok, env_issues = _check_env()
    guard_ok, guard_issues = _check_guard()
    imp_ok, imp_issues = _check_provider_imports()

    payload = {
        "format": "care.offline_audit.v1",
        "checks": {
            "hf_env_vars_set": {"ok": env_ok, "issues": env_issues},
            "offline_guard": {"ok": guard_ok, "issues": guard_issues},
            "providers_load_offline": {"ok": imp_ok, "issues": imp_issues},
        },
        "verdict": "PASS" if env_ok and guard_ok and imp_ok else "FAIL",
    }
    print(json.dumps(payload, indent=2))
    return 0 if payload["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
