"""Direct-call tests for read-only API endpoints (Phase 6)."""
from __future__ import annotations

from pathlib import Path

from care.api.routes_health import health
from care.api.routes_offline import offline_status
from care.api.routes_plugins import list_plugins
from care.core.config import AppConfig, PIISection


def test_health_returns_status_ok() -> None:
    payload = health()
    assert payload["status"] == "ok"
    assert payload["app"] == "care"
    assert isinstance(payload["version"], str)


def test_offline_status_includes_expected_hf_env() -> None:
    payload = offline_status(config=AppConfig())
    assert "offline_guard_enabled" in payload
    assert "expected_hf_env" in payload
    expected = payload["expected_hf_env"]
    assert expected["HF_HUB_OFFLINE"] == "1"
    assert expected["TRANSFORMERS_OFFLINE"] == "1"


def test_list_plugins_returns_ocr_pii_and_documentai_chains() -> None:
    payload = list_plugins(config=AppConfig())
    assert "ocr" in payload
    assert "pii" in payload
    assert "document_ai" in payload
    # Default config: VLM disabled, OCR=mock_ocr, PII=regex.
    assert payload["document_ai"]["enabled"] is False
    assert payload["ocr"]["active_chain"] == ["mock_ocr"]
    assert payload["pii"]["active_chain"] == ["regex"]
    # Optional providers must NOT be enabled_by_default.
    name_default = {
        p["name"]: p["enabled_by_default"]
        for p in payload["pii"]["providers"]
    }
    assert name_default.get("piiranha") is False
    name_default_vlm = {
        p["name"]: p["enabled_by_default"]
        for p in payload["document_ai"]["providers"]
    }
    assert name_default_vlm.get("kosmos25") is False


def test_list_plugins_does_not_leak_model_paths() -> None:
    """The plugins endpoint must NOT return model paths or other config
    keys that could disclose filesystem layout."""
    payload = list_plugins(config=AppConfig())
    for category in ("ocr", "pii", "document_ai"):
        for p in payload[category]["providers"]:
            assert "model_path" not in p
            assert "model_dir" not in p
            assert "tessdata_dir" not in p
            assert "checksums" not in p


def test_list_plugins_exposes_per_provider_status_fields() -> None:
    """Every provider summary must include the new operational status
    fields the GUI needs to render an honest enable/disable view."""
    payload = list_plugins(config=AppConfig())
    required_fields = {
        "enabled",
        "in_active_chain",
        "model_files_present",
        "license_review_required",
    }
    for category in ("ocr", "pii", "document_ai"):
        for p in payload[category]["providers"]:
            missing = required_fields - set(p.keys())
            assert not missing, f"{category}.{p['name']} missing {missing}"


def test_list_plugins_marks_piiranha_as_license_review_required() -> None:
    payload = list_plugins(config=AppConfig())
    by_name = {p["name"]: p for p in payload["pii"]["providers"]}
    assert by_name["piiranha"]["license_review_required"] is True
    # MIT-licensed counterparts must NOT be flagged for review.
    assert by_name["roberta_ner"]["license_review_required"] is False
    assert by_name["regex"]["license_review_required"] is False


def test_list_plugins_in_active_chain_reflects_chain_membership() -> None:
    payload = list_plugins(config=AppConfig())
    by_name = {p["name"]: p for p in payload["pii"]["providers"]}
    # Default chain is ["regex"].
    assert by_name["regex"]["in_active_chain"] is True
    assert by_name["roberta_ner"]["in_active_chain"] is False
    assert by_name["piiranha"]["in_active_chain"] is False


def test_list_plugins_enabled_reflects_provider_config_flag() -> None:
    cfg = AppConfig(
        pii=PIISection(
            provider_chain=["regex", "roberta_ner"],
            providers={
                "roberta_ner": {"enabled": True},
                "piiranha": {"enabled": False},
            },
        )
    )
    payload = list_plugins(config=cfg)
    by_name = {p["name"]: p for p in payload["pii"]["providers"]}
    assert by_name["roberta_ner"]["enabled"] is True
    assert by_name["roberta_ner"]["in_active_chain"] is True
    assert by_name["piiranha"]["enabled"] is False
    assert by_name["piiranha"]["in_active_chain"] is False


def test_list_plugins_model_files_present_detects_real_dir(tmp_path: Path) -> None:
    """When model_dir points at a populated HF-style checkpoint, the
    endpoint reports model_files_present=True; when missing, False;
    when no model_dir is configured, None."""
    populated = tmp_path / "roberta"
    populated.mkdir()
    (populated / "config.json").write_text("{}", encoding="utf-8")

    empty_dir = tmp_path / "piiranha-empty"
    empty_dir.mkdir()  # no config.json -> incomplete

    cfg = AppConfig(
        pii=PIISection(
            provider_chain=["regex"],
            providers={
                "roberta_ner": {"model_dir": str(populated)},
                "piiranha": {"model_dir": str(empty_dir)},
                "presidio": {"model_dir": str(tmp_path / "missing")},
            },
        )
    )
    payload = list_plugins(config=cfg)
    by_name = {p["name"]: p for p in payload["pii"]["providers"]}
    assert by_name["roberta_ner"]["model_files_present"] is True
    assert by_name["piiranha"]["model_files_present"] is False
    assert by_name["presidio"]["model_files_present"] is False
    # regex needs no model files; reports None.
    assert by_name["regex"]["model_files_present"] is None
