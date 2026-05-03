"""LayoutLM plugin (Phase 10) — disabled-by-default, offline-only,
suggestion-only, review-gated.

Names follow the test list specified for Phase 10.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from care.core.config import AppConfig
from care.core.constants import (
    BLOCKING_QA_FLAGS,
    HF_OFFLINE_ENV,
    QA_FLAGS,
    REVIEW_REQUIRED_QA_FLAGS,
)
from care.core.errors import ConfigError, OfflineGuardError
from care.document_ai.providers.layoutlm_provider import LayoutLMProvider
from care.document_ai.registry import get_registry, reset_registry


# ----- helpers ----------------------------------------------------------


def _stub_model_dir(tmp_path: Path) -> Path:
    """Create a minimal local 'model dir' shape so the plugin's path
    check passes. Real `transformers` loading is exercised in the
    Phase 7 packaging tests where actual model files are available."""
    model_dir = tmp_path / "models" / "layoutlm"
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "vocab.txt").write_text("[PAD]\n", encoding="utf-8")
    return model_dir


def _base_config(model_dir: Path) -> dict[str, Any]:
    return {
        "model_dir": str(model_dir),
        "processor_dir": str(model_dir),
        "local_files_only": True,
        "allow_network": False,
        "variant": "layoutlm-base-uncased",
    }


# ----- 1. test_layoutlm_provider_disabled_by_default -------------------


def test_layoutlm_provider_disabled_by_default() -> None:
    """The plugin class declares enabled_by_default=False AND no path
    in default config or default chain enables it."""
    assert LayoutLMProvider.enabled_by_default is False
    cfg = AppConfig()
    # Default document_ai section: not enabled, empty chain.
    assert cfg.document_ai.enabled is False
    assert "layoutlm" not in cfg.document_ai.provider_chain


def test_layoutlm_registered_in_document_ai_registry() -> None:
    reset_registry()
    try:
        registry = get_registry()
        assert registry.has("layoutlm")
        assert registry.get("layoutlm") is LayoutLMProvider
    finally:
        reset_registry()


# ----- 2. test_layoutlm_rejects_allow_network_true ---------------------


def test_layoutlm_rejects_allow_network_true(tmp_path: Path) -> None:
    provider = LayoutLMProvider()
    cfg = _base_config(_stub_model_dir(tmp_path))
    cfg["allow_network"] = True
    with pytest.raises(ConfigError, match="allow_network"):
        provider.load(cfg)


# ----- 3. test_layoutlm_rejects_local_files_only_false ----------------


def test_layoutlm_rejects_local_files_only_false(tmp_path: Path) -> None:
    provider = LayoutLMProvider()
    cfg = _base_config(_stub_model_dir(tmp_path))
    cfg["local_files_only"] = False
    with pytest.raises(ConfigError, match="local_files_only"):
        provider.load(cfg)


# ----- 4. test_layoutlm_missing_model_dir_fails_closed ---------------


def test_layoutlm_missing_model_dir_fails_closed(tmp_path: Path) -> None:
    """A missing model_dir must raise OfflineGuardError, not attempt
    a download. This is the single most important offline-safety
    behavior of the plugin."""
    provider = LayoutLMProvider()
    cfg = {
        "model_dir": str(tmp_path / "no_such_dir"),
        "processor_dir": str(tmp_path / "no_such_dir"),
        "local_files_only": True,
        "allow_network": False,
    }
    with pytest.raises(OfflineGuardError, match="model_dir not found"):
        provider.load(cfg)


def test_layoutlm_missing_processor_dir_fails_closed(tmp_path: Path) -> None:
    model_dir = _stub_model_dir(tmp_path)
    provider = LayoutLMProvider()
    cfg = {
        "model_dir": str(model_dir),
        "processor_dir": str(tmp_path / "ghost_processor"),
        "local_files_only": True,
        "allow_network": False,
    }
    with pytest.raises(OfflineGuardError, match="processor_dir not found"):
        provider.load(cfg)


# ----- 5. test_layoutlm_sets_hf_offline_env_vars ----------------------


def test_layoutlm_sets_hf_offline_env_vars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plugin must (re-)set every HF offline env var on load. Even if
    the global guard already did so, the plugin must not trust that
    state — it sets them itself."""
    for key in HF_OFFLINE_ENV:
        monkeypatch.delenv(key, raising=False)

    model_dir = _stub_model_dir(tmp_path)
    provider = LayoutLMProvider()
    try:
        provider.load(_base_config(model_dir))
    except ConfigError as exc:
        # Acceptable failure: transformers not installed in CI. The
        # env-var assertions still hold because they happen BEFORE the
        # transformers import in load().
        if "transformers is not installed" not in str(exc):
            raise
    for key, expected in HF_OFFLINE_ENV.items():
        assert os.environ.get(key) == expected


# ----- 6. test_layoutlm_manifest_includes_model_checksums --------------


def test_layoutlm_manifest_includes_model_checksums(tmp_path: Path) -> None:
    """The manifest reports per-file SHA-256s of every file under
    model_dir. Required for tamper detection at deploy time."""
    model_dir = _stub_model_dir(tmp_path)
    provider = LayoutLMProvider()
    try:
        provider.load(_base_config(model_dir))
    except ConfigError as exc:
        if "transformers is not installed" not in str(exc):
            raise
    manifest = provider.get_model_manifest()
    assert "model_checksums" in manifest
    # Every file we created in _stub_model_dir must appear with a hex sha256.
    assert "config.json" in manifest["model_checksums"]
    assert "vocab.txt" in manifest["model_checksums"]
    for digest in manifest["model_checksums"].values():
        assert len(digest) == 64
        int(digest, 16)  # valid hex


# ----- 7. test_layoutlm_manifest_marks_review_required ----------------


def test_layoutlm_manifest_marks_review_required(tmp_path: Path) -> None:
    """The plugin's manifest declares the review/redaction posture.
    These fields are the system-of-record auditors will check.
    Renaming them is a breaking change."""
    model_dir = _stub_model_dir(tmp_path)
    provider = LayoutLMProvider()
    try:
        provider.load(_base_config(model_dir))
    except ConfigError as exc:
        if "transformers is not installed" not in str(exc):
            raise
    manifest = provider.get_model_manifest()
    assert manifest["provider_name"] == "layoutlm"
    assert manifest["provider_type"] == "document_layout_model"
    assert manifest["model_path"] == str(model_dir)
    assert manifest["model_path_present"] is True
    assert manifest["requires_network"] is False
    assert manifest["enabled_by_default"] is False
    assert manifest["generative_model"] is False
    assert manifest["hallucination_risk"] is False
    assert manifest["requires_review"] is True
    assert manifest["safe_for_image_redaction"] is False
    assert manifest["local_files_only"] is True
    assert manifest["hf_offline_env"] == dict(HF_OFFLINE_ENV)
    # MIT (v1) → no license-review-required
    assert manifest["license"] == "MIT"
    assert manifest["license_review_required"] is False
    assert "LAYOUTLM_PLUGIN_USED" in manifest["qa_flags_emitted_on_use"]
    assert "LAYOUTLM_REQUIRES_REVIEW" in manifest["qa_flags_emitted_on_use"]


def test_layoutlm_v3_manifest_marks_license_review_required(tmp_path: Path) -> None:
    """v3 is CC BY-NC-SA 4.0 (NonCommercial). The manifest must
    surface this so commercial deployments get a clear hard stop."""
    model_dir = _stub_model_dir(tmp_path)
    provider = LayoutLMProvider()
    cfg = _base_config(model_dir)
    cfg["variant"] = "layoutlmv3-base"
    try:
        provider.load(cfg)
    except ConfigError as exc:
        if "transformers is not installed" not in str(exc):
            raise
    manifest = provider.get_model_manifest()
    assert manifest["license"] == "CC BY-NC-SA 4.0"
    assert manifest["license_review_required"] is True
    assert "LAYOUTLM_LICENSE_REVIEW_REQUIRED" in manifest["qa_flags_emitted_on_use"]


# ----- 8. test_layoutlm_not_used_by_default_pipeline ------------------


def test_layoutlm_not_used_by_default_pipeline(tmp_path: Path) -> None:
    """The default config never enables layoutlm and never lists it
    in the chain. A default pipeline run must not instantiate it."""
    from care.workers.pipeline import _instantiate_vlm_chain

    cfg = AppConfig()
    # Default: document_ai.enabled=False, provider_chain=[]
    chain = _instantiate_vlm_chain(cfg)
    assert chain == []  # nothing instantiated


# ----- 9. test_layoutlm_suggestion_requires_review --------------------


def test_layoutlm_suggestion_requires_review() -> None:
    """When any LAYOUTLM_* QA flag is in the report, the QA gate must
    set requires_human_review=True even if no flag in the set is in
    BLOCKING_QA_FLAGS. This is the keystone of the review-gated
    suggestion-only rule.

    The plugin is a document_ai provider, so its flags surface through
    the same vlm_warnings channel used by Kosmos-2.5 and friends.
    """
    from care.document_ir.models import Warning as IRWarning
    from care.extraction.diagram_extractor import DiagramExtraction
    from care.extraction.narrative_extractor import NarrativeExtraction
    from care.review.qa_flags import build_qa_report
    from care.templates.detector import (
        TemplateMatch,
        TemplateMatchEvidence,
    )

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
        image_path="/work/diagram.png",
        confidence=0.9,
        requires_review=False,
        warnings=[],
    )
    narrative = NarrativeExtraction(
        page_index=0,
        text="some narrative",
        anchor_start="Narrative",
        anchor_end="Officer",
        anchor_start_found=True,
        anchor_end_found=True,
        confidence=0.9,
        requires_review=False,
        warnings=[],
    )
    vlm_warnings = [
        IRWarning(code="LAYOUTLM_PLUGIN_USED", message="suggestion produced"),
        IRWarning(code="LAYOUTLM_REGION_SUGGESTION", message="region proposed"),
    ]
    report = build_qa_report(
        match, diagram, narrative, vlm_warnings=vlm_warnings
    )
    assert report.requires_human_review is True
    assert "LAYOUTLM_PLUGIN_USED" in report.qa_flags
    # Export must NOT be blocked by the LAYOUTLM_* flags themselves.
    assert report.export_blocked is False
    for flag in (
        "LAYOUTLM_PLUGIN_USED",
        "LAYOUTLM_REGION_SUGGESTION",
        "LAYOUTLM_FALLBACK_USED",
        "LAYOUTLM_CONFLICT_WITH_TEMPLATE",
        "LAYOUTLM_REQUIRES_REVIEW",
        "LAYOUTLM_LICENSE_REVIEW_REQUIRED",
    ):
        assert flag not in BLOCKING_QA_FLAGS, (
            f"{flag} must NOT be a blocking flag — LayoutLM is review-gated, "
            "not export-blocking."
        )


def test_review_required_qa_flags_set_includes_layoutlm() -> None:
    for flag in (
        "LAYOUTLM_PLUGIN_USED",
        "LAYOUTLM_REGION_SUGGESTION",
        "LAYOUTLM_FALLBACK_USED",
        "LAYOUTLM_CONFLICT_WITH_TEMPLATE",
        "LAYOUTLM_REQUIRES_REVIEW",
    ):
        assert flag in REVIEW_REQUIRED_QA_FLAGS


def test_layoutlm_qa_flags_are_in_qa_flag_vocabulary() -> None:
    for flag in (
        "LAYOUTLM_PLUGIN_USED",
        "LAYOUTLM_REGION_SUGGESTION",
        "LAYOUTLM_FALLBACK_USED",
        "LAYOUTLM_CONFLICT_WITH_TEMPLATE",
        "LAYOUTLM_REQUIRES_REVIEW",
        "LAYOUTLM_LICENSE_REVIEW_REQUIRED",
    ):
        assert flag in QA_FLAGS


# ----- 10. test_layoutlm_output_cannot_drive_image_redaction ----------


def test_layoutlm_output_cannot_drive_image_redaction(tmp_path: Path) -> None:
    """The plugin's manifest declares safe_for_image_redaction=False.
    No code path may set it True. This is the structural guarantee
    that LayoutLM bbox suggestions never substitute for OCR/native
    word coordinates when blackening pixels."""
    model_dir = _stub_model_dir(tmp_path)
    provider = LayoutLMProvider()
    try:
        provider.load(_base_config(model_dir))
    except ConfigError as exc:
        if "transformers is not installed" not in str(exc):
            raise
    manifest = provider.get_model_manifest()
    assert manifest["safe_for_image_redaction"] is False
    # The class attribute also declares this — defense in depth.
    assert provider.supports_region_detection is True
    assert provider.supports_image_to_text is False  # never produces page text


# ----- 11. test_model_manifest_includes_layoutlm_disabled_by_default --


def test_model_manifest_includes_layoutlm_disabled_by_default(
    tmp_path: Path,
) -> None:
    """A pre-load manifest (i.e. without the operator having enabled
    the plugin) still surfaces enabled_by_default=False so an audit
    that scans `get_model_manifest()` on every registered class can
    verify default safety posture."""
    provider = LayoutLMProvider()
    manifest = provider.get_model_manifest()
    assert manifest["provider_name"] == "layoutlm"
    assert manifest["enabled_by_default"] is False
    assert manifest["requires_network"] is False
    assert manifest["model_path_present"] is False  # not loaded yet


# ----- 12. test_governance_check_passes_after_layoutlm_plugin -----------


def test_governance_check_passes_after_layoutlm_plugin() -> None:
    """The policy checker must continue to pass with the new plugin
    in place. We invoke the script as a subprocess so the test reflects
    what CI runs, not just an in-process import."""
    import subprocess
    import sys

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
