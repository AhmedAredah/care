"""Phase 2 pipeline must run end-to-end with the offline guard active."""
from __future__ import annotations

from pathlib import Path

from care.core import offline_guard
from care.core.config import AppConfig
from care.workers.pipeline import run_pipeline
from tests._fixtures import make_digital_pdf, make_synthetic_image


def _config_for(tmp_path: Path) -> AppConfig:
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    cfg.paths.export_dir = str(tmp_path / "exports")
    return cfg


def test_pipeline_runs_under_offline_guard_on_image(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_synthetic_image(inputs / "scan.png")

    offline_guard.enable()
    try:
        result = run_pipeline(inputs, config=_config_for(tmp_path))
        assert len(result.artifacts) == 1
        assert result.artifacts[0].text_source == "ocr"
    finally:
        offline_guard.disable()


def test_pipeline_runs_under_offline_guard_on_pdf(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    make_digital_pdf(inputs / "d.pdf")

    offline_guard.enable()
    try:
        result = run_pipeline(inputs, config=_config_for(tmp_path))
        assert len(result.artifacts) == 1
        assert result.artifacts[0].text_source == "native"
    finally:
        offline_guard.disable()
