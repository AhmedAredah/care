"""Run scripts/governance_check.py as a subprocess and assert it passes."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_governance_check_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "governance_check.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"governance_check.py failed:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "Policy check passed." in result.stdout


def test_default_config_disables_optional_plugins() -> None:
    """Piiranha, Kosmos-2.5, and document_ai must be disabled by default."""
    import yaml  # type: ignore[import-not-found]

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    assert cfg["pii"]["providers"]["piiranha"]["enabled"] is False
    assert cfg["document_ai"]["providers"]["kosmos25"]["enabled"] is False
    assert cfg["document_ai"]["enabled"] is False


def test_governance_check_imports_runtime_immutable_table() -> None:
    """The script and routes_config.py must agree on which keys are
    locked. A divergence is a CONTRACT enforcement gap."""
    import sys

    sys.path.insert(0, str(ROOT))
    from care.core.governance_guard import (
        IMMUTABLE_RULES,
        check_immutable_violations,
    )

    # The script literally imports check_immutable_violations — if
    # the runtime ever drops it, the script's import would fail
    # (covered by test_governance_check_script_passes). Belt-and-braces:
    # confirm the table is non-empty so a future "let's empty it"
    # refactor trips this test, not just the script's import.
    assert len(IMMUTABLE_RULES) >= 5
    # Quick smoke that the helper still works.
    assert check_immutable_violations({}) == []


def test_required_files_exist() -> None:
    required = [
        "care/ocr/base.py",
        "care/ocr/registry.py",
        "care/document_ai/base.py",
        "care/document_ai/registry.py",
        "care/pii/base.py",
        "care/pii/registry.py",
        "care/document_ir/models.py",
        "care/workers/pipeline.py",
        "docs/offline-mode.md",
        "docs/plugin-system.md",
        "docs/document-ai-plugins.md",
        "docs/pii-policy.md",
    ]
    for rel in required:
        assert (ROOT / rel).exists(), f"missing required file: {rel}"
