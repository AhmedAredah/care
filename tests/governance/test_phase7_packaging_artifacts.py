"""Policy-level tests for Phase 7 packaging artifacts."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


REQUIRED_DOCS = [
    "docs/architecture.md",
    "docs/security.md",
    "docs/template-authoring.md",
    "docs/redaction.md",
    "docs/evaluation.md",
    "docs/deployment.md",
    "docs/packaging.md",
    "docs/license-and-model-governance.md",
    "docs/no-network-guarantee.md",
    "docs/offline-mode.md",
    "docs/plugin-system.md",
    "docs/document-ai-plugins.md",
    "docs/pii-policy.md",
]

REQUIRED_PACKAGING_SCRIPTS = [
    "scripts/build_wheelhouse.sh",
    "scripts/verify_no_network.py",
    "scripts/generate_sbom.sh",
    "scripts/package_offline_installer.sh",
    "scripts/compute_model_checksums.py",
    "scripts/scan_frontend_external_assets.py",
]

REQUIRED_MODEL_READMES = [
    "models/README.md",
    "models/ocr/paddleocr/README.md",
    "models/ocr/tesseract/README.md",
    "models/pii/presidio/README.md",
    "models/pii/piiranha/README.md",
    "models/document_ai/kosmos-2.5/README.md",
]


def test_required_docs_exist_and_nonempty() -> None:
    for rel in REQUIRED_DOCS:
        path = REPO_ROOT / rel
        assert path.exists(), f"missing required doc: {rel}"
        assert path.stat().st_size > 64, f"doc too small: {rel}"


def test_required_packaging_scripts_exist() -> None:
    for rel in REQUIRED_PACKAGING_SCRIPTS:
        path = REPO_ROOT / rel
        assert path.exists(), f"missing required packaging script: {rel}"


def test_required_model_readmes_exist() -> None:
    for rel in REQUIRED_MODEL_READMES:
        path = REPO_ROOT / rel
        assert path.exists(), f"missing model README: {rel}"


def test_packaging_scripts_have_no_network_at_run_time() -> None:
    """Shell scripts named *_offline_*, verify_no_network, and
    generate_sbom must NOT contain `curl`/`wget`/`pip install` calls
    that would reach a non-loopback target."""
    forbidden = ["curl ", "wget ", "pip install "]
    for rel in [
        "scripts/verify_no_network.py",
        "scripts/generate_sbom.sh",
        "scripts/package_offline_installer.sh",
        "scripts/compute_model_checksums.py",
        "scripts/scan_frontend_external_assets.py",
    ]:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for bad in forbidden:
            assert bad not in text, (
                f"packaging script {rel} must not invoke '{bad.strip()}'"
            )


def test_no_real_model_files_committed() -> None:
    """The repo must commit ONLY README placeholders under models/.

    We ask git which files are tracked rather than scanning the
    filesystem — operators legitimately download local model
    checkpoints into ``models/<plugin>/`` to test plugins, and those
    untracked files must not trip this rule.
    """
    import subprocess

    result = subprocess.run(
        ["git", "ls-files", "models"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        # Not a git checkout (e.g. unpacked tarball) — skip.
        import pytest

        pytest.skip(f"git ls-files unavailable: {result.stderr.strip()}")
    tracked = [
        line.strip() for line in result.stdout.splitlines() if line.strip()
    ]
    bad = [f for f in tracked if not f.endswith(".md")]
    assert not bad, f"non-README model files committed: {bad}"
