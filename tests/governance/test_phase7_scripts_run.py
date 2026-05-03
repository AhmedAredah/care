"""Smoke tests that each Phase 7 script actually executes."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _python() -> str:
    return sys.executable


def test_compute_model_checksums_walks_a_directory(tmp_path) -> None:
    (tmp_path / "weights.bin").write_bytes(b"abc")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "tokenizer.json").write_bytes(b"def")
    out = subprocess.run(
        [_python(), str(REPO_ROOT / "scripts" / "compute_model_checksums.py"), str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert out.returncode == 0, out.stdout + out.stderr
    payload = json.loads(out.stdout)
    assert payload["format"] == "care.model_checksums.v1"
    assert payload["file_count"] == 2
    assert "weights.bin" in payload["checksums"]


def test_scan_frontend_external_assets_runs_against_repo() -> None:
    out = subprocess.run(
        [_python(), str(REPO_ROOT / "scripts" / "scan_frontend_external_assets.py")],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert out.returncode == 0, out.stdout + out.stderr
    payload = json.loads(out.stdout)
    assert payload["external_url_count"] == 0


def test_verify_no_network_runs_and_emits_audit() -> None:
    """verify_no_network.py exits 0 in this offline-first environment.
    The check ensures the script ran end to end (env, guard, providers)."""
    out = subprocess.run(
        [_python(), str(REPO_ROOT / "scripts" / "verify_no_network.py")],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        env={**os.environ, **{
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
        }},
    )
    assert out.returncode == 0, out.stdout + out.stderr
    payload = json.loads(out.stdout)
    assert payload["verdict"] == "PASS"
    assert payload["checks"]["hf_env_vars_set"]["ok"] is True
    assert payload["checks"]["offline_guard"]["ok"] is True
    assert payload["checks"]["providers_load_offline"]["ok"] is True


def test_cli_generate_sbom_writes_json(tmp_path) -> None:
    out_path = tmp_path / "sbom.json"
    out = subprocess.run(
        [_python(), "-m", "care.cli", "generate-sbom",
         "--output", str(out_path),
         "--models-dir", str(tmp_path / "no_such_dir")],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert out.returncode == 0, out.stdout + out.stderr
    assert out_path.exists()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["format"] == "care.sbom.v1"
    assert payload["dependency_count"] >= 1
    assert "licenses" in payload
    assert "model_manifest" in payload


def test_cli_model_manifest_writes_json(tmp_path) -> None:
    (tmp_path / "ocr" / "demo").mkdir(parents=True)
    (tmp_path / "ocr" / "demo" / "weights.bin").write_bytes(b"x")
    out_path = tmp_path / "manifest.json"
    out = subprocess.run(
        [_python(), "-m", "care.cli", "model-manifest",
         "--output", str(out_path),
         "--models-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert out.returncode == 0, out.stdout + out.stderr
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["format"] == "care.model_manifest.v1"
    assert any(
        p["provider_name"] == "demo" for p in payload["groups"]["ocr"]
    )
