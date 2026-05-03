"""Config endpoints (Phase 13.1 + 13.2 + 13.3 + 13.6)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from care.api.routes_config import (
    delete_secret_by_name,
    derive_secret_name,
    get_config,
    get_config_schema,
    get_config_source,
    get_locked_keys,
    get_restart_required,
    get_secrets_list,
    patch_config,
    post_secret,
    validate_config,
)
from care.core.config import AppConfig, LLMSection, PIISection, ServerConfig


def test_get_config_returns_full_dump() -> None:
    payload = get_config(config=AppConfig())
    # Top-level sections every consumer of the GUI should see.
    for section in (
        "offline",
        "server",
        "paths",
        "ocr",
        "document_ai",
        "pii",
        "llm",
        "template_detection",
        "extraction",
        "review",
        "export",
        "logging",
    ):
        assert section in payload, f"missing section {section}"


def test_get_config_redacts_api_keys() -> None:
    cfg = AppConfig(
        llm=LLMSection(
            providers={
                "openai": {
                    "enabled": False,
                    "api_key": "sk-secret-xyz",
                    "model": "gpt-4o-mini",
                },
            },
        )
    )
    payload = get_config(config=cfg)
    openai = payload["llm"]["providers"]["openai"]
    assert openai["api_key"] == "***REDACTED***"
    # Non-secret fields are preserved verbatim.
    assert openai["model"] == "gpt-4o-mini"


def test_get_config_does_not_redact_model_dirs() -> None:
    """Model dirs are operator-supplied filesystem locations — not
    secrets — and the GUI needs them to show "where on disk is this
    plugin's checkpoint?" """
    cfg = AppConfig(
        pii=PIISection(
            providers={
                "roberta_ner": {
                    "enabled": False,
                    "model_dir": "/abs/path/to/roberta",
                },
            },
        )
    )
    payload = get_config(config=cfg)
    assert (
        payload["pii"]["providers"]["roberta_ner"]["model_dir"]
        == "/abs/path/to/roberta"
    )


def test_get_config_schema_is_pydantic_json_schema() -> None:
    schema = get_config_schema()
    # JSON Schema discriminator: must have a $defs / properties pair.
    assert isinstance(schema, dict)
    assert "properties" in schema
    # AppConfig has top-level properties for every YAML section.
    for key in ("offline", "server", "paths", "ocr", "pii"):
        assert key in schema["properties"], f"schema missing {key}"


def test_get_config_source_returns_none_when_no_file_found(
    monkeypatch, tmp_path: Path
) -> None:
    """When run from a directory without config.yaml, the endpoint
    reports defaults-only mode."""
    monkeypatch.chdir(tmp_path)
    # Patch DEFAULT_CONFIG_PATHS so it can't accidentally find a
    # config.yaml elsewhere in the repo.
    from care.api import routes_config as mod

    monkeypatch.setattr(mod, "DEFAULT_CONFIG_PATHS", [tmp_path / "missing.yaml"])
    payload = get_config_source()
    assert payload["exists"] is False
    assert payload["is_default"] is True
    assert payload["path"] is None


def test_get_config_source_reports_existing_file(
    monkeypatch, tmp_path: Path
) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("offline:\n  enabled: true\n", encoding="utf-8")
    from care.api import routes_config as mod

    monkeypatch.setattr(mod, "DEFAULT_CONFIG_PATHS", [cfg_path])
    payload = get_config_source()
    assert payload["exists"] is True
    assert payload["is_default"] is False
    assert payload["path"] == str(cfg_path.resolve())


# ----- Phase 13.2 ------------------------------------------------------


def test_get_locked_keys_returns_immutable_rules() -> None:
    payload = get_locked_keys()
    assert "locked_keys" in payload
    paths = {row["path"] for row in payload["locked_keys"]}
    assert "logging.log_raw_pii" in paths
    assert "export.include_original_pdf" in paths


def test_validate_config_accepts_safe_patch() -> None:
    """A patch that only flips a benign provider's enabled flag is
    legal: ok=True, no errors."""
    result = validate_config(
        body={"pii": {"providers": {"roberta_ner": {"enabled": True}}}},
        current=AppConfig(),
    )
    assert result["ok"] is True
    assert result["pydantic_errors"] == []
    assert result["governance_errors"] == []


def test_validate_config_rejects_immutable_violation() -> None:
    result = validate_config(
        body={"logging": {"log_raw_pii": True}},
        current=AppConfig(),
    )
    assert result["ok"] is False
    assert any("log_raw_pii" in e for e in result["governance_errors"])
    assert result["pydantic_errors"] == []


def test_validate_config_reports_pydantic_errors_on_type_mismatch() -> None:
    """If the operator submits a value Pydantic can't coerce, the
    validate endpoint surfaces a structured error rather than 500.

    Pydantic v2 leniently coerces strings like "no"/"yes" to bool, so
    we use a clearly invalid integer for ``server.port`` (must be int).
    """
    result = validate_config(
        body={"server": {"port": "definitely-not-a-number"}},
        current=AppConfig(),
    )
    assert result["ok"] is False
    assert result["pydantic_errors"]
    assert any("port" in e["loc"] for e in result["pydantic_errors"])


def test_validate_config_can_report_both_kinds_of_errors() -> None:
    """An operator who flips multiple things at once should see all
    relevant failures, not just the first."""
    result = validate_config(
        body={
            "logging": {"log_raw_pii": True},
            "export": {"include_original_pdf": True},
            "server": {"port": "not-an-int"},
        },
        current=AppConfig(),
    )
    assert result["ok"] is False
    # logging.log_raw_pii=True and export.include_original_pdf=True
    # are policy violations.
    assert len(result["governance_errors"]) >= 2
    # server.port="not-an-int" is a Pydantic type error.
    assert any("port" in e["loc"] for e in result["pydantic_errors"])


def test_validate_config_merges_with_current_state() -> None:
    """A partial patch must not erase fields it didn't touch."""
    current = AppConfig(
        pii=PIISection(
            provider_chain=["regex"],
            providers={"regex": {"enabled": True}},
        )
    )
    result = validate_config(
        body={"pii": {"providers": {"roberta_ner": {"enabled": True}}}},
        current=current,
    )
    # Must succeed: regex stays enabled, roberta_ner gets added.
    assert result["ok"] is True


# ----- Phase 13.3 — PATCH endpoint -------------------------------------


def _patch_to_tmp_config(monkeypatch, tmp_path: Path, initial_yaml: str) -> Path:
    """Redirect the writer to a temporary config file."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(initial_yaml, encoding="utf-8")
    from care.core import config_writer

    monkeypatch.setattr(
        config_writer,
        "resolve_write_path",
        lambda *a, **kw: cfg_path,
    )
    return cfg_path


def test_patch_config_writes_and_returns_redacted_state(
    monkeypatch, tmp_path: Path
) -> None:
    cfg_path = _patch_to_tmp_config(
        monkeypatch,
        tmp_path,
        "# top-of-file note\nllm:\n  providers:\n    openai:\n      enabled: false\n      api_key: \"\"\n",
    )
    response = patch_config(
        body={"llm": {"providers": {"openai": {"api_key": "sk-test-secret"}}}},
        current=AppConfig(),
    )
    assert response["ok"] is True
    assert response["target_path"] == str(cfg_path.resolve())
    # File written, comment preserved
    body = cfg_path.read_text(encoding="utf-8")
    assert "# top-of-file note" in body
    assert "sk-test-secret" in body  # disk has the real value
    # Response is redacted
    openai_response = response["config"]["llm"]["providers"]["openai"]
    assert openai_response["api_key"] == "***REDACTED***"


def test_patch_config_rejects_immutable_violation(
    monkeypatch, tmp_path: Path
) -> None:
    cfg_path = _patch_to_tmp_config(
        monkeypatch, tmp_path, "logging:\n  log_raw_pii: false\n"
    )
    with pytest.raises(HTTPException) as exc:
        patch_config(
            body={"logging": {"log_raw_pii": True}},
            current=AppConfig(),
        )
    assert exc.value.status_code == 400
    detail = exc.value.detail
    assert isinstance(detail, dict)
    assert any("log_raw_pii" in e for e in detail["governance_errors"])
    # File untouched
    assert "log_raw_pii: false" in cfg_path.read_text(encoding="utf-8")


def test_patch_config_rejects_pydantic_error(
    monkeypatch, tmp_path: Path
) -> None:
    cfg_path = _patch_to_tmp_config(
        monkeypatch, tmp_path, "server:\n  port: 7860\n"
    )
    with pytest.raises(HTTPException) as exc:
        patch_config(
            body={"server": {"port": "not-a-number"}},
            current=AppConfig(),
        )
    assert exc.value.status_code == 400
    assert exc.value.detail["pydantic_errors"]
    # File untouched
    assert "port: 7860" in cfg_path.read_text(encoding="utf-8")


def test_patch_config_creates_backup_when_file_existed(
    monkeypatch, tmp_path: Path
) -> None:
    cfg_path = _patch_to_tmp_config(
        monkeypatch, tmp_path, "server:\n  port: 7860\n"
    )
    response = patch_config(
        body={"server": {"port": 7861}},
        current=AppConfig(),
    )
    assert response["backup_path"] is not None
    assert Path(response["backup_path"]).exists()


def test_patch_config_empty_body_is_a_noop_with_audit_backup(
    monkeypatch, tmp_path: Path
) -> None:
    cfg_path = _patch_to_tmp_config(
        monkeypatch, tmp_path, "server:\n  port: 7860\n"
    )
    response = patch_config(body={}, current=AppConfig())
    assert response["ok"] is True
    # File still has the same logical content; backup created.
    assert response["backup_path"] is not None
    assert "port: 7860" in cfg_path.read_text(encoding="utf-8")


# ----- Phase 13.6 — secrets sidecar -----------------------------------


def _redirect_secrets(monkeypatch, tmp_path: Path) -> Path:
    secrets_path = tmp_path / "secrets.yaml"
    from care.api import routes_config as mod

    monkeypatch.setattr(mod, "_secrets_path", lambda: secrets_path)
    return secrets_path


def test_post_secret_writes_and_returns_name_only(
    monkeypatch, tmp_path: Path
) -> None:
    sp = _redirect_secrets(monkeypatch, tmp_path)
    response = post_secret(body={"name": "OPENAI_API_KEY", "value": "sk-test"})
    assert response["ok"] is True
    assert response["name"] == "OPENAI_API_KEY"
    assert response["placeholder"] == "${secret:OPENAI_API_KEY}"
    # The value MUST NOT appear anywhere in the response.
    assert "sk-test" not in str(response)
    # It IS on disk though.
    assert "sk-test" in sp.read_text(encoding="utf-8")


def test_post_secret_rejects_bad_name(
    monkeypatch, tmp_path: Path
) -> None:
    _redirect_secrets(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as exc:
        post_secret(body={"name": "lowercase", "value": "x"})
    assert exc.value.status_code == 400


def test_post_secret_rejects_empty_value(
    monkeypatch, tmp_path: Path
) -> None:
    _redirect_secrets(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as exc:
        post_secret(body={"name": "FOO", "value": ""})
    assert exc.value.status_code == 400


def test_get_secrets_list_returns_names_only(
    monkeypatch, tmp_path: Path
) -> None:
    _redirect_secrets(monkeypatch, tmp_path)
    post_secret(body={"name": "A_KEY", "value": "v1"})
    post_secret(body={"name": "B_KEY", "value": "v2"})
    listing = get_secrets_list()
    assert listing["names"] == ["A_KEY", "B_KEY"]
    # No values in the response payload.
    assert "v1" not in str(listing)
    assert "v2" not in str(listing)


def test_delete_secret_removes_from_sidecar(
    monkeypatch, tmp_path: Path
) -> None:
    sp = _redirect_secrets(monkeypatch, tmp_path)
    post_secret(body={"name": "FOO", "value": "v1"})
    post_secret(body={"name": "BAR", "value": "v2"})
    delete_secret_by_name(name="FOO")
    assert "FOO" not in sp.read_text(encoding="utf-8")
    assert "BAR" in sp.read_text(encoding="utf-8")


def test_delete_secret_404_when_missing(
    monkeypatch, tmp_path: Path
) -> None:
    _redirect_secrets(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as exc:
        delete_secret_by_name(name="MISSING_KEY")
    assert exc.value.status_code == 404


def test_derive_secret_name_for_provider_path() -> None:
    response = derive_secret_name(path="llm.providers.openai.api_key")
    assert response["secret_name"] == "OPENAI_API_KEY"
    assert response["placeholder"] == "${secret:OPENAI_API_KEY}"


def test_derive_secret_name_for_unknown_path() -> None:
    response = derive_secret_name(path="server.host")
    assert response["secret_name"] is None
    assert response["placeholder"] is None


# ----- Phase 13.7 — restart-required signal ----------------------------


def test_restart_required_returns_unknown_when_snapshot_empty() -> None:
    from care.api.routes_config import get_restart_required
    from care.core.runtime_state import clear_boot_snapshot

    clear_boot_snapshot()
    response = get_restart_required(config=AppConfig())
    assert response["pending_restart"] is None
    assert response["boot_snapshot"] is None
    assert "server.host" in response["requires_restart_paths"]
    clear_boot_snapshot()


def test_restart_required_false_when_snapshot_matches_disk() -> None:
    from care.api.routes_config import get_restart_required
    from care.core.config import ServerConfig
    from care.core.runtime_state import (
        clear_boot_snapshot,
        set_boot_snapshot,
    )

    clear_boot_snapshot()
    set_boot_snapshot(host="127.0.0.1", port=7860, expose_to_network=False)
    cfg = AppConfig(server=ServerConfig(host="127.0.0.1", port=7860, expose_to_network=False))
    response = get_restart_required(config=cfg)
    assert response["pending_restart"] is False
    assert response["pending_changes"] == []
    clear_boot_snapshot()


def test_restart_required_flags_drift_with_specific_paths() -> None:
    from care.api.routes_config import get_restart_required
    from care.core.config import ServerConfig
    from care.core.runtime_state import (
        clear_boot_snapshot,
        set_boot_snapshot,
    )

    clear_boot_snapshot()
    set_boot_snapshot(host="127.0.0.1", port=7860, expose_to_network=False)
    cfg = AppConfig(server=ServerConfig(host="127.0.0.1", port=7861, expose_to_network=False))
    response = get_restart_required(config=cfg)
    assert response["pending_restart"] is True
    assert len(response["pending_changes"]) == 1
    diff = response["pending_changes"][0]
    assert diff["path"] == "server.port"
    assert diff["boot_value"] == 7860
    assert diff["current_value"] == 7861
    clear_boot_snapshot()


def test_load_config_resolves_secret_placeholders(
    monkeypatch, tmp_path: Path
) -> None:
    """End-to-end: a placeholder in config.yaml gets replaced by the
    sidecar value when load_config() is called."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "llm:\n"
        "  providers:\n"
        "    openai:\n"
        "      enabled: false\n"
        "      api_key: \"${secret:OPENAI_API_KEY}\"\n",
        encoding="utf-8",
    )
    secrets_path = tmp_path / "secrets.yaml"
    from care.core.secrets import save_secret

    save_secret(secrets_path, "OPENAI_API_KEY", "sk-resolved")

    from care.core.config import load_config

    cfg = load_config(cfg_path)
    assert cfg.llm.providers["openai"]["api_key"] == "sk-resolved"
