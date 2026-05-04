"""Phase 12 — vendor-agnostic LLM/VLM provider plugin layer.

Covers all 10 prescribed test areas:

1. Cloud providers disabled by default.
2. Cloud providers rejected in offline mode.
3. Local providers must use localhost unless explicitly allowed.
4. LLM output cannot drive export.
5. LLM output cannot drive image redaction.
6. LLM suggestions require review.
7. Provider manifest does not leak API keys.
8. Config rejects API keys in logs.
9. Mock provider works for tests.
10. governance_check.py passes.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from care.core.config import AppConfig
from care.core.constants import (
    BLOCKING_QA_FLAGS,
    QA_FLAGS,
    REVIEW_REQUIRED_QA_FLAGS,
)
from care.core.errors import ConfigError, OfflineGuardError
from care.llm import LLMProvider, get_registry, reset_registry
from care.llm.base import PROVIDER_TYPES
from care.llm.providers.anthropic_provider import AnthropicProvider
from care.llm.providers.gemini_provider import GeminiProvider
from care.llm.providers.hf_local_provider import HFLocalProvider
from care.llm.providers.llamacpp_provider import LlamaCppProvider
from care.llm.providers.mock_llm_provider import MockLLMProvider
from care.llm.providers.ollama_provider import OllamaProvider
from care.llm.providers.openai_provider import OpenAIProvider
from care.llm.providers.vllm_provider import VLLMProvider

CLOUD_PROVIDERS = [OpenAIProvider, GeminiProvider, AnthropicProvider]
LOCAL_SERVER_PROVIDERS = [OllamaProvider, VLLMProvider, LlamaCppProvider]
ALL_PROVIDER_CLASSES = (
    CLOUD_PROVIDERS + LOCAL_SERVER_PROVIDERS + [HFLocalProvider, MockLLMProvider]
)


# ----- 1. cloud providers disabled by default ---------------------------


def test_cloud_providers_disabled_by_default() -> None:
    """The class declares enabled_by_default=False AND the default
    AppConfig leaves the LLM section off entirely."""
    for cls in CLOUD_PROVIDERS:
        assert cls.enabled_by_default is False
        assert cls.requires_network is True
        assert cls.provider_type == "cloud_llm_provider"
    cfg = AppConfig()
    assert cfg.llm.enabled is False
    assert cfg.llm.provider_chain == []


def test_all_providers_disabled_by_default() -> None:
    """No concrete provider class — cloud, local, or mock — can be
    enabled by default. This is enforced at the class level so a
    config typo can never silently flip a provider on."""
    for cls in ALL_PROVIDER_CLASSES:
        assert cls.enabled_by_default is False, cls


def test_provider_types_in_known_set() -> None:
    """Every concrete class declares a provider_type in the
    enumerated set. A typo here would be caught at registry init,
    but explicit assertion locks the expectation."""
    for cls in ALL_PROVIDER_CLASSES:
        assert cls.provider_type in PROVIDER_TYPES, cls


# ----- 2. cloud providers rejected in offline mode ----------------------


@pytest.mark.parametrize("cls", CLOUD_PROVIDERS)
def test_cloud_provider_rejected_in_offline_mode(cls) -> None:
    provider = cls()
    cfg = {
        "api_key": "sk-test",
        "acknowledged_external_data_egress": True,
        "_app_config": {"offline_enabled": True},
    }
    with pytest.raises(OfflineGuardError, match="offline"):
        provider.load(cfg)


@pytest.mark.parametrize("cls", CLOUD_PROVIDERS)
def test_cloud_provider_requires_egress_acknowledgement(cls) -> None:
    """A cloud provider must refuse to load until the operator
    explicitly acknowledges that data leaves the local environment.
    Sending PII to a third party silently is not acceptable."""
    provider = cls()
    cfg = {
        "api_key": "sk-test",
        "_app_config": {"offline_enabled": False},
    }
    with pytest.raises(ConfigError, match="acknowledged_external_data_egress"):
        provider.load(cfg)


@pytest.mark.parametrize("cls", CLOUD_PROVIDERS)
def test_cloud_provider_requires_api_key(cls) -> None:
    provider = cls()
    cfg = {
        "acknowledged_external_data_egress": True,
        "_app_config": {"offline_enabled": False},
    }
    with pytest.raises(ConfigError, match="api_key"):
        provider.load(cfg)


# ----- 3. local providers must use localhost unless explicitly allowed --


@pytest.mark.parametrize("cls", LOCAL_SERVER_PROVIDERS)
def test_local_server_default_endpoint_is_loopback(cls) -> None:
    provider = cls()
    provider.load({})  # picks default_endpoint
    assert "127.0.0.1" in provider._endpoint or "localhost" in provider._endpoint
    manifest = provider.get_model_manifest()
    assert manifest["endpoint_type"] == "loopback"


@pytest.mark.parametrize("cls", LOCAL_SERVER_PROVIDERS)
def test_local_server_rejects_non_loopback_without_opt_in(cls) -> None:
    provider = cls()
    with pytest.raises(ConfigError, match="not loopback"):
        provider.load({"endpoint_url": "http://10.0.0.5:11434"})


@pytest.mark.parametrize("cls", LOCAL_SERVER_PROVIDERS)
def test_local_server_non_loopback_blocked_in_offline_mode(cls) -> None:
    """Even with allow_non_loopback=true, offline mode wins. Cloud
    blocking and offline blocking are layered guards, not
    alternatives."""
    provider = cls()
    with pytest.raises(OfflineGuardError):
        provider.load({
            "endpoint_url": "http://10.0.0.5:11434",
            "allow_non_loopback": True,
            "_app_config": {"offline_enabled": True},
        })


@pytest.mark.parametrize("cls", LOCAL_SERVER_PROVIDERS)
def test_local_server_non_loopback_allowed_with_opt_in_and_no_offline(cls) -> None:
    provider = cls()
    provider.load({
        "endpoint_url": "http://10.0.0.5:11434",
        "allow_non_loopback": True,
        "_app_config": {"offline_enabled": False},
    })
    assert provider._loaded
    manifest = provider.get_model_manifest()
    # Manifest reflects elevated risk: not loopback + opt-in → external.
    assert manifest["sends_data_external"] is True


# ----- 4. LLM output cannot drive export --------------------------------


@pytest.mark.parametrize("cls", ALL_PROVIDER_CLASSES)
def test_provider_manifest_marks_export_unsafe(cls) -> None:
    """Class-level invariant: no provider may declare itself safe
    for export decisions. The pipeline must never use LLM output as
    the deciding factor for ALLOW vs BLOCK."""
    assert cls.safe_for_export_decision is False, cls


# ----- 5. LLM output cannot drive image redaction -----------------------


@pytest.mark.parametrize("cls", ALL_PROVIDER_CLASSES)
def test_provider_manifest_marks_image_redaction_unsafe(cls) -> None:
    """Class-level invariant: no provider may declare itself safe
    for image redaction. LLM bbox suggestions never substitute for
    OCR/native word coordinates when blackening pixels."""
    assert cls.safe_for_image_redaction is False, cls


# ----- 6. LLM suggestions require review --------------------------------


def test_llm_qa_flags_in_review_required_set() -> None:
    """Every Phase 12 LLM_* QA flag is in REVIEW_REQUIRED_QA_FLAGS,
    so when any of them appears in a report, build_qa_report sets
    requires_human_review=True."""
    for flag in (
        "LLM_PROVIDER_USED",
        "LLM_REGION_SUGGESTION",
        "LLM_ANCHOR_SUGGESTION",
        "LLM_QA_SECOND_OPINION",
        "LLM_EXTERNAL_PROVIDER_USED",
        "LLM_REQUIRES_REVIEW",
        "LLM_OUTPUT_UNMAPPED",
        "LLM_CONFLICT_WITH_TEMPLATE",
    ):
        assert flag in QA_FLAGS, flag
        assert flag in REVIEW_REQUIRED_QA_FLAGS, flag
        # Critical: NO LLM flag may be a blocking flag — the gate
        # for blocking is template/PII/diagram/narrative, not LLM.
        assert flag not in BLOCKING_QA_FLAGS, flag


def test_llm_flag_in_qa_report_forces_review() -> None:
    """When an LLM_* flag travels with the report (via vlm_warnings),
    requires_human_review flips to True."""
    from care.document_ir.models import Warning as IRWarning
    from care.extraction.diagram_extractor import DiagramExtraction
    from care.extraction.narrative_extractor import NarrativeExtraction
    from care.review.qa_flags import build_qa_report
    from care.templates.detector import TemplateMatch, TemplateMatchEvidence

    match = TemplateMatch(
        template_id="example",
        version="1.0",
        confidence=0.95,
        evidence=TemplateMatchEvidence(page_count=1, page_count_in_range=True),
    )
    diagram = DiagramExtraction(
        page_index=0,
        bbox_norm=(0.0, 0.0, 1.0, 0.5),
        bbox_pixels=(0, 0, 100, 50),
        image_path="/work/d.png",
        confidence=0.9,
        requires_review=False,
        warnings=[],
    )
    narrative = NarrativeExtraction(
        page_index=0,
        text="ok",
        anchor_start="N",
        anchor_end="O",
        anchor_start_found=True,
        anchor_end_found=True,
        confidence=0.9,
        requires_review=False,
        warnings=[],
    )
    vlm_warnings = [
        IRWarning(code="LLM_PROVIDER_USED", message=""),
        IRWarning(code="LLM_REGION_SUGGESTION", message=""),
    ]
    report = build_qa_report(match, diagram, narrative, vlm_warnings=vlm_warnings)
    assert report.requires_human_review is True
    assert report.export_blocked is False  # LLM flags don't block
    assert "LLM_PROVIDER_USED" in report.qa_flags


# ----- 7. provider manifest does not leak API keys ----------------------


@pytest.mark.parametrize("cls", CLOUD_PROVIDERS)
def test_cloud_provider_manifest_redacts_api_key(cls) -> None:
    provider = cls()
    cfg = {
        "api_key": "sk-PLAINTEXT-NEVER-LOG",
        "acknowledged_external_data_egress": True,
        "model": "test-model",
        "_app_config": {"offline_enabled": False},
    }
    try:
        provider.load(cfg)
    except ConfigError as exc:
        # Acceptable: vendor SDK not installed in CI. Manifest still
        # callable on an unloaded instance; it will just lack model.
        if "is not installed" not in str(exc):
            raise
    manifest = provider.get_model_manifest()
    blob = json.dumps(manifest)
    assert "sk-PLAINTEXT-NEVER-LOG" not in blob
    assert "***REDACTED***" in blob or manifest.get("config", {}).get("api_key") in (
        None, "***REDACTED***"
    )


def test_local_server_manifest_does_not_leak_arbitrary_credentials() -> None:
    provider = OllamaProvider()
    provider.load({
        "endpoint_url": "http://127.0.0.1:11434",
        "auth_token": "should-be-redacted",
    })
    manifest = provider.get_model_manifest()
    blob = json.dumps(manifest)
    assert "should-be-redacted" not in blob


# ----- 8. config rejects API keys in logs -------------------------------


def test_provider_repr_does_not_leak_api_key(caplog) -> None:
    """Logging the manifest must not expose the api_key. We exercise
    the logger path explicitly: emit the manifest at INFO level and
    grep the captured log."""
    provider = OpenAIProvider()
    cfg = {
        "api_key": "sk-PLAINTEXT-NEVER-LOG",
        "acknowledged_external_data_egress": True,
        "_app_config": {"offline_enabled": False},
    }
    try:
        provider.load(cfg)
    except ConfigError as exc:
        if "is not installed" not in str(exc):
            raise
    with caplog.at_level(logging.INFO):
        logging.getLogger("audit").info("manifest=%s", provider.get_model_manifest())
    assert "sk-PLAINTEXT-NEVER-LOG" not in caplog.text


# ----- 9. mock provider works for tests --------------------------------


def test_mock_provider_loads_and_returns_text() -> None:
    provider = MockLLMProvider()
    provider.load({"fixture": {"text": "hello world"}})
    out = provider.generate_text("prompt")
    assert out.text == "hello world"
    assert out.provider == "mock_llm"
    assert out.requires_review is True


def test_mock_provider_supports_vision_path() -> None:
    provider = MockLLMProvider()
    provider.load({})
    out = provider.analyze_image("/tmp/x.png", "what's in this image?")
    assert "mock vision" in (out.text or "")


def test_mock_provider_manifest_has_safety_fields() -> None:
    provider = MockLLMProvider()
    provider.load({})
    m = provider.get_model_manifest()
    assert m["enabled_by_default"] is False
    assert m["safe_for_export_decision"] is False
    assert m["safe_for_image_redaction"] is False
    assert m["sends_data_external"] is False


# ----- 10. governance_check passes --------------------------------------


def test_governance_check_passes_with_llm_layer() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/governance_check.py"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"governance_check.py failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "Policy check passed" in result.stdout


# ----- registry parity -------------------------------------------------


def test_registry_lists_all_providers() -> None:
    reset_registry()
    try:
        registry = get_registry()
        for name in (
            "openai",
            "gemini",
            "anthropic",
            "ollama",
            "vllm",
            "llamacpp",
            "hf_local",
            "mock_llm",
        ):
            assert registry.has(name)
            cls = registry.get(name)
            assert issubclass(cls, LLMProvider)
    finally:
        reset_registry()


def test_registry_rejects_unknown_provider() -> None:
    from care.core.errors import PluginNotFoundError

    reset_registry()
    try:
        with pytest.raises(PluginNotFoundError):
            get_registry().get("definitely_not_a_real_vendor")
    finally:
        reset_registry()


# ----- HF local provider behaves like other transformers plugins ------


def test_hf_local_rejects_allow_network() -> None:
    provider = HFLocalProvider()
    with pytest.raises(ConfigError, match="allow_network"):
        provider.load({"allow_network": True, "model_dir": "/tmp"})


def test_hf_local_rejects_local_files_only_false() -> None:
    provider = HFLocalProvider()
    with pytest.raises(ConfigError, match="local_files_only"):
        provider.load({"local_files_only": False, "model_dir": "/tmp"})


def test_hf_local_missing_model_dir_fails_closed(tmp_path: Path) -> None:
    provider = HFLocalProvider()
    with pytest.raises(OfflineGuardError, match="model_dir not found"):
        provider.load({"model_dir": str(tmp_path / "no_such_dir")})
