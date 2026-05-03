"""SBOM / model manifest / license report emitter tests (Phase 7)."""
from __future__ import annotations

from pathlib import Path

from care.audit import (
    build_license_report,
    build_model_manifest,
    build_sbom,
)


def test_build_sbom_returns_versioned_envelope() -> None:
    payload = build_sbom()
    assert payload["format"] == "care.sbom.v1"
    assert payload["app"]["name"] == "care"
    assert isinstance(payload["app"]["version"], str)
    assert "generated_at" in payload
    assert payload["dependency_count"] == len(payload["dependencies"])


def test_build_sbom_includes_dependencies_with_license() -> None:
    payload = build_sbom()
    assert payload["dependency_count"] > 0
    # fastapi, pydantic, pillow, pypdfium2, pyyaml are runtime deps.
    names = {d["name"].lower() for d in payload["dependencies"]}
    expected = {"fastapi", "pydantic", "pillow", "pypdfium2", "pyyaml"}
    assert expected <= names, f"missing expected deps: {expected - names}"
    for d in payload["dependencies"]:
        assert "version" in d and d["version"]
        assert "license" in d


def test_build_sbom_no_packages_mode_strips_dependencies() -> None:
    payload = build_sbom(include_packages=False)
    assert payload["dependencies"] == []
    assert payload["dependency_count"] == 0
    # Model manifest section still present.
    assert "model_manifest" in payload


def test_build_sbom_uses_provided_models_dir(tmp_path: Path) -> None:
    (tmp_path / "ocr" / "fake_provider").mkdir(parents=True)
    (tmp_path / "ocr" / "fake_provider" / "weights.bin").write_bytes(b"abc")
    payload = build_sbom(models_dir=tmp_path)
    groups = payload["model_manifest"]["groups"]
    fake = [p for p in groups.get("ocr", []) if p["provider_name"] == "fake_provider"]
    assert fake, "fake_provider must appear under ocr group"
    assert fake[0]["file_count"] == 1
    assert "weights.bin" in fake[0]["model_checksums"]


def test_model_manifest_for_known_kosmos25_provider(tmp_path: Path) -> None:
    """Real registered providers (paddleocr, presidio, kosmos25) must
    surface their declared metadata when their model dir exists."""
    (tmp_path / "document_ai" / "kosmos25").mkdir(parents=True)
    (tmp_path / "document_ai" / "kosmos25" / "model.bin").write_bytes(b"x")
    payload = build_model_manifest(models_dir=tmp_path)
    entries = payload["groups"]["document_ai"]
    matching = [e for e in entries if e["provider_name"] == "kosmos25"]
    assert matching, "kosmos25 must appear when a directory exists"
    meta = matching[0]["metadata"]
    assert meta["registered"] is True
    assert meta["enabled_by_default"] is False
    assert meta["generative_model"] is True
    assert meta["hallucination_risk"] is True


def test_model_manifest_when_models_dir_missing(tmp_path: Path) -> None:
    target = tmp_path / "no_such_dir"
    payload = build_model_manifest(models_dir=target)
    assert payload["format"] == "care.model_manifest.v1"
    for group in ("ocr", "pii", "document_ai"):
        assert payload["groups"][group] == []


def test_license_report_compresses_multiline_license_to_first_line() -> None:
    distributions = [
        {"name": "alpha", "version": "1", "license": "MIT\n\nFull text..."},
        {"name": "beta", "version": "1", "license": ""},
        {"name": "gamma", "version": "1", "license": "Apache-2.0"},
    ]
    report = build_license_report(distributions)
    assert report["package_count"] == 3
    assert report["by_package"]["alpha"] == "MIT"
    assert report["by_package"]["beta"] == "UNKNOWN"
    assert report["by_package"]["gamma"] == "Apache-2.0"
    assert report["counts_by_license"]["MIT"] == 1
    assert report["counts_by_license"]["UNKNOWN"] == 1


def test_sbom_records_optional_providers_disabled_by_default(tmp_path: Path) -> None:
    """piiranha and kosmos25 must surface enabled_by_default=False even
    when the model dir is present (so an auditor can confirm the
    provider stays opt-in)."""
    for path in [
        tmp_path / "pii" / "piiranha",
        tmp_path / "document_ai" / "kosmos25",
    ]:
        path.mkdir(parents=True)
        (path / "weights.bin").write_bytes(b"x")
    payload = build_sbom(models_dir=tmp_path)
    pii_entries = payload["model_manifest"]["groups"]["pii"]
    vlm_entries = payload["model_manifest"]["groups"]["document_ai"]
    pir = [e for e in pii_entries if e["provider_name"] == "piiranha"]
    kos = [e for e in vlm_entries if e["provider_name"] == "kosmos25"]
    assert pir and kos
    assert pir[0]["metadata"]["enabled_by_default"] is False
    assert kos[0]["metadata"]["enabled_by_default"] is False
