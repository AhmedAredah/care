"""Secrets sidecar (Phase 13.6)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from care.core.secrets import (
    SECRETS_FILENAME,
    delete_secret,
    derive_name_for_path,
    is_valid_secret_name,
    list_secret_names,
    load_secrets,
    resolve_placeholders,
    resolve_secrets_path,
    save_secret,
)


# ----- name validation --------------------------------------------------


@pytest.mark.parametrize("name", [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "FOO_1",
    "X",
])
def test_is_valid_secret_name_accepts_screaming_snake(name: str) -> None:
    assert is_valid_secret_name(name) is True


@pytest.mark.parametrize("name", [
    "openai_api_key",   # lowercase
    "Openai_Key",       # mixed
    "1FOO",             # leading digit
    "FOO-BAR",          # dash
    "FOO BAR",          # space
    "",
    None,
])
def test_is_valid_secret_name_rejects_anything_else(name) -> None:
    assert is_valid_secret_name(name) is False


# ----- save / load / delete --------------------------------------------


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    save_secret(p, "OPENAI_API_KEY", "sk-test-123")
    save_secret(p, "ANTHROPIC_API_KEY", "anth-456")
    loaded = load_secrets(p)
    assert loaded["OPENAI_API_KEY"] == "sk-test-123"
    assert loaded["ANTHROPIC_API_KEY"] == "anth-456"


def test_save_secret_rejects_bad_name(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    with pytest.raises(ValueError, match="must match"):
        save_secret(p, "lowercase_name", "x")


def test_save_secret_overwrites_existing_key(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    save_secret(p, "FOO", "v1")
    save_secret(p, "FOO", "v2")
    assert load_secrets(p) == {"FOO": "v2"}


def test_delete_secret_returns_true_when_removed(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    save_secret(p, "FOO", "v1")
    save_secret(p, "BAR", "v2")
    assert delete_secret(p, "FOO") is True
    assert load_secrets(p) == {"BAR": "v2"}


def test_delete_secret_returns_false_when_missing(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    save_secret(p, "FOO", "v1")
    assert delete_secret(p, "BAR") is False
    assert load_secrets(p) == {"FOO": "v1"}


def test_list_secret_names_is_sorted(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    save_secret(p, "B_KEY", "1")
    save_secret(p, "A_KEY", "2")
    assert list_secret_names(p) == ["A_KEY", "B_KEY"]


def test_load_secrets_missing_file_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    assert load_secrets(p) == {}


@pytest.mark.skipif(os.name != "posix", reason="POSIX-only chmod check")
def test_save_secret_sets_user_only_perms(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    save_secret(p, "FOO", "v1")
    mode = p.stat().st_mode & 0o777
    assert mode == 0o600


def test_windows_acl_helper_invokes_icacls_correctly(monkeypatch, tmp_path: Path) -> None:
    """The Windows branch of _try_chmod_user_only must call icacls
    with the right argv. Tested without depending on os.name=='nt'
    by exercising the helper directly."""
    from care.core import secrets as secrets_mod

    captured: list[list[str]] = []

    class _FakeCompleted:
        returncode = 0
        stdout = b""
        stderr = b""

    def fake_run(argv, *args, **kwargs):
        captured.append(list(argv))
        return _FakeCompleted()

    target = tmp_path / "secrets.yaml"
    target.write_text("ok: true\n", encoding="utf-8")
    monkeypatch.setenv("USERNAME", "ahmed")
    monkeypatch.setattr("subprocess.run", fake_run)
    secrets_mod._apply_windows_user_only_acl(target)
    assert len(captured) == 1
    argv = captured[0]
    assert argv[0] == "icacls"
    assert str(target) in argv
    assert "/inheritance:r" in argv
    assert "/grant:r" in argv
    assert "ahmed:F" in argv


def test_windows_acl_helper_skips_when_username_missing(monkeypatch, tmp_path: Path) -> None:
    from care.core import secrets as secrets_mod

    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("USER", raising=False)
    called = {"yes": False}

    def fake_run(*args, **kwargs):
        called["yes"] = True
        raise AssertionError("icacls should not be called without USERNAME")

    monkeypatch.setattr("subprocess.run", fake_run)
    # Should return cleanly without raising.
    secrets_mod._apply_windows_user_only_acl(tmp_path / "secrets.yaml")
    assert called["yes"] is False


def test_atomic_write_no_tmp_left_behind(tmp_path: Path) -> None:
    p = tmp_path / "secrets.yaml"
    save_secret(p, "FOO", "v1")
    leftovers = list(tmp_path.glob("*.tmp"))
    assert leftovers == []


# ----- placeholder resolution ------------------------------------------


def test_resolve_placeholders_replaces_known_names() -> None:
    cfg = {
        "llm": {
            "providers": {
                "openai": {"api_key": "${secret:OPENAI_API_KEY}"},
                "anthropic": {"api_key": "${secret:ANTHROPIC_API_KEY}"},
            }
        }
    }
    secrets = {
        "OPENAI_API_KEY": "sk-real",
        "ANTHROPIC_API_KEY": "anth-real",
    }
    out = resolve_placeholders(cfg, secrets)
    assert out["llm"]["providers"]["openai"]["api_key"] == "sk-real"
    assert out["llm"]["providers"]["anthropic"]["api_key"] == "anth-real"


def test_resolve_placeholders_leaves_unknown_in_place() -> None:
    cfg = {"foo": "${secret:UNKNOWN}"}
    out = resolve_placeholders(cfg, {})
    assert out["foo"] == "${secret:UNKNOWN}"


def test_resolve_placeholders_does_not_recurse_into_strings() -> None:
    """A bare value with no placeholder must round-trip unchanged."""
    cfg = {"foo": "literal value"}
    out = resolve_placeholders(cfg, {"FOO": "anything"})
    assert out == cfg


def test_resolve_placeholders_walks_lists() -> None:
    cfg = {"chain": ["${secret:A}", "literal", "${secret:B}"]}
    out = resolve_placeholders(cfg, {"A": "alpha", "B": "beta"})
    assert out == {"chain": ["alpha", "literal", "beta"]}


# ----- name derivation --------------------------------------------------


@pytest.mark.parametrize("path,expected", [
    ("llm.providers.openai.api_key", "OPENAI_API_KEY"),
    ("llm.providers.anthropic.api_key", "ANTHROPIC_API_KEY"),
    ("llm.providers.gemini.api_key", "GEMINI_API_KEY"),
])
def test_derive_name_for_path_known_shape(path: str, expected: str) -> None:
    assert derive_name_for_path(path) == expected


@pytest.mark.parametrize("path", [
    "offline.enabled",            # not a provider field
    "server.host",                # not a provider field
    "llm.enabled",                # provider section but not a leaf
    "llm.providers.openai",       # missing field part
])
def test_derive_name_for_path_returns_none_for_non_provider_paths(path: str) -> None:
    assert derive_name_for_path(path) is None


# ----- sibling path ----------------------------------------------------


def test_resolve_secrets_path_is_sibling(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    assert resolve_secrets_path(cfg) == tmp_path / SECRETS_FILENAME
