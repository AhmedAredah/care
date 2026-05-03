"""CLI smoke tests (Phase 6).

Each subcommand is invoked through ``care.cli.run`` so we can
assert exit codes and JSON output without spawning a subprocess.
"""
from __future__ import annotations

import json
from pathlib import Path

from care.cli import run
from tests._fixtures import (
    make_digital_pdf,
    make_example_template_pdf,
    make_synthetic_image,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_cli_lists_every_required_command() -> None:
    """The CLI must register every documented command."""
    from care.cli.main import build_parser

    parser = build_parser()
    sub = next(
        (
            a
            for a in parser._actions  # noqa: SLF001
            if a.dest == "command"
        ),
        None,
    )
    assert sub is not None
    cmds = set(sub.choices.keys())
    expected = {
        "process",
        "inspect",
        "list-plugins",
        "verify-offline",
        "validate-template",
        "serve",
        "compute-model-checksums",
        "generate-sbom",
        "scan-frontend-assets",
    }
    missing = expected - cmds
    assert not missing, f"missing CLI commands: {missing}"


def test_cli_list_plugins_emits_json(capsys) -> None:
    rc = run(["list-plugins"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert {"ocr", "document_ai", "pii"} <= set(payload.keys())


def test_cli_inspect_pdf_emits_inspection(tmp_path, capsys) -> None:
    p = make_digital_pdf(tmp_path / "d.pdf")
    rc = run(["inspect", str(p)])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["file_type"] == "pdf"
    assert payload["page_count"] >= 1


def test_cli_verify_offline_reports_status(capsys) -> None:
    rc = run(["verify-offline"])
    payload = json.loads(capsys.readouterr().out)
    # rc may be 0 (offline guard enabled) or 1 (issues); both are valid for
    # this assertion. We only require structured output.
    assert rc in (0, 1)
    assert "offline_guard_enabled" in payload
    assert "issues" in payload


def test_cli_validate_template_against_example(capsys) -> None:
    target = REPO_ROOT / "templates" / "example_state" / "example_template_v1.yaml"
    rc = run(["validate-template", str(target)])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["valid"] is True
    assert payload["template_id"]
    assert payload["regions"]


def test_cli_compute_model_checksums(tmp_path, capsys) -> None:
    (tmp_path / "weights.bin").write_bytes(b"abc")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "tokenizer.json").write_bytes(b"def")
    rc = run(["compute-model-checksums", str(tmp_path)])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert "weights.bin" in payload["checksums"]
    assert any(k.endswith("tokenizer.json") for k in payload["checksums"])


def test_cli_scan_frontend_assets_passes_against_repo(capsys) -> None:
    rc = run(["scan-frontend-assets", str(REPO_ROOT / "frontend")])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["external_url_count"] == 0


def test_cli_process_runs_pipeline_and_returns_zero(tmp_path, capsys) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")
    rc = run(
        [
            "process",
            str(inputs),
            "--work-dir",
            str(tmp_path / "work"),
            "--export-dir",
            str(tmp_path / "exports"),
            "--templates-dir",
            str(REPO_ROOT / "templates"),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["files_processed"] == 1
    assert len(payload["reports"]) == 1


def test_cli_process_fail_on_block_returns_one(tmp_path, capsys) -> None:
    """An unknown-template file must cause --fail-on-block to exit 1."""
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    # Use the unknown template fixture so the pipeline blocks export.
    from tests._fixtures import make_unknown_template_pdf

    make_unknown_template_pdf(inputs / "random.pdf")
    rc = run(
        [
            "process",
            str(inputs),
            "--work-dir",
            str(tmp_path / "work"),
            "--export-dir",
            str(tmp_path / "exports"),
            "--templates-dir",
            str(REPO_ROOT / "templates"),
            "--fail-on-block",
        ]
    )
    capsys.readouterr()
    assert rc == 1


def test_cli_generate_sbom_emits_v1_sbom(tmp_path, capsys) -> None:
    out_path = tmp_path / "sbom.json"
    rc = run([
        "generate-sbom",
        "--output", str(out_path),
        "--models-dir", str(tmp_path / "no_such_dir"),
    ])
    capsys.readouterr()
    assert rc == 0
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["format"] == "care.sbom.v1"
    assert payload["app"]["name"] == "care"
    assert "dependencies" in payload
    assert "model_manifest" in payload
    assert "licenses" in payload
