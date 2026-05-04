"""Phase 12 — LLM safety helpers."""
from __future__ import annotations

import pytest

from care.core.errors import ConfigError, OfflineGuardError
from care.llm.safety import (
    assert_loopback_or_explicit,
    is_loopback_url,
    redact_secrets,
    reject_in_offline_mode,
)

# ----- is_loopback_url ----------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        ("http://localhost:11434", True),
        ("http://127.0.0.1:8000", True),
        ("http://127.0.0.1", True),
        ("http://[::1]:8080", True),
        ("https://localhost", True),
        ("http://api.openai.com", False),
        ("http://10.0.0.1:11434", False),
        ("http://192.168.1.5", False),
        # 0.0.0.0 binds every interface; NOT loopback from the kernel's view.
        ("http://0.0.0.0:8000", False),
        ("", False),
        (None, False),
        ("not a url", False),
    ],
)
def test_is_loopback_url(url, expected) -> None:
    assert is_loopback_url(url) is expected


# ----- redact_secrets -----------------------------------------------------


def test_redact_secrets_strips_api_key_field() -> None:
    out = redact_secrets({"api_key": "sk-XYZ", "model": "gpt-4o"})
    assert out["api_key"] == "***REDACTED***"
    assert out["model"] == "gpt-4o"


def test_redact_secrets_preserves_absence_signal() -> None:
    """Empty/None secret fields stay None so an auditor can see "no
    api_key configured" without a redacted placeholder confusing them
    into thinking one exists."""
    out = redact_secrets({"api_key": None, "token": "", "model": "gpt-4o"})
    assert out["api_key"] is None
    assert out["token"] is None


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "API_KEY",
        "apikey",
        "auth_token",
        "bearer",
        "auth",
        "secret",
        "password",
        "openai_api_key",
        "credential",
        "vendor_credential",
    ],
)
def test_redact_secrets_pattern_covers_common_key_names(key: str) -> None:
    out = redact_secrets({key: "value"})
    assert out[key] == "***REDACTED***"


def test_redact_secrets_recurses_into_nested_dicts() -> None:
    payload = {
        "config": {
            "model": "gpt",
            "credentials": {"api_key": "sk-XYZ"},
        },
        "models": [
            {"name": "claude", "auth": "secret-token"},
        ],
    }
    out = redact_secrets(payload)
    assert out["config"]["credentials"]["api_key"] == "***REDACTED***"
    assert out["models"][0]["auth"] == "***REDACTED***"
    assert out["models"][0]["name"] == "claude"


def test_redact_secrets_does_not_modify_input() -> None:
    payload = {"api_key": "sk-XYZ"}
    out = redact_secrets(payload)
    assert payload["api_key"] == "sk-XYZ"  # original untouched
    assert out["api_key"] == "***REDACTED***"


def test_redact_secrets_extra_keys() -> None:
    out = redact_secrets(
        {"custom_field": "x", "model": "y"}, extra_keys=("custom_field",)
    )
    assert out["custom_field"] == "***REDACTED***"
    assert out["model"] == "y"


# ----- reject_in_offline_mode --------------------------------------------


def test_reject_in_offline_mode_raises_for_cloud_in_offline() -> None:
    with pytest.raises(OfflineGuardError, match="offline"):
        reject_in_offline_mode("openai", requires_network=True, offline_enabled=True)


def test_reject_in_offline_mode_passes_for_local_in_offline() -> None:
    reject_in_offline_mode("ollama", requires_network=False, offline_enabled=True)


def test_reject_in_offline_mode_passes_for_cloud_when_offline_off() -> None:
    reject_in_offline_mode("openai", requires_network=True, offline_enabled=False)


# ----- assert_loopback_or_explicit ----------------------------------------


def test_assert_loopback_passes_for_loopback() -> None:
    assert_loopback_or_explicit(
        "ollama",
        endpoint_url="http://127.0.0.1:11434",
        allow_non_loopback=False,
        offline_enabled=True,  # loopback is fine in offline mode
    )


def test_assert_loopback_rejects_remote_without_opt_in() -> None:
    with pytest.raises(ConfigError, match="not loopback"):
        assert_loopback_or_explicit(
            "ollama",
            endpoint_url="http://api.example.com",
            allow_non_loopback=False,
            offline_enabled=False,
        )


def test_assert_loopback_remote_allowed_with_opt_in_when_online() -> None:
    """Operator explicitly opts into a remote local-server URL AND
    offline mode is off → the call passes. Even then the manifest
    will reflect the elevated risk via sends_data_external."""
    assert_loopback_or_explicit(
        "ollama",
        endpoint_url="http://10.0.0.5:11434",
        allow_non_loopback=True,
        offline_enabled=False,
    )


def test_assert_loopback_remote_blocked_with_opt_in_when_offline() -> None:
    """Even with the operator's opt-in, offline mode wins. Both
    safety guards must agree before a non-loopback URL is allowed."""
    with pytest.raises(OfflineGuardError):
        assert_loopback_or_explicit(
            "ollama",
            endpoint_url="http://10.0.0.5:11434",
            allow_non_loopback=True,
            offline_enabled=True,
        )


def test_assert_loopback_rejects_empty_url() -> None:
    with pytest.raises(ConfigError, match="endpoint_url"):
        assert_loopback_or_explicit(
            "ollama",
            endpoint_url=None,
            allow_non_loopback=False,
            offline_enabled=False,
        )
