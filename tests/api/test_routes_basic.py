"""Direct-call tests for read-only API endpoints (Phase 6)."""
from __future__ import annotations

from pathlib import Path

from care.api.routes_health import health
from care.api.routes_offline import offline_status
from care.api.routes_plugins import list_plugins
from care.core.config import AppConfig, OCRSection, PIISection


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


def test_list_plugins_accuracy_field_always_present() -> None:
    """Every provider summary exposes an ``accuracy`` key — either a
    sanitised payload or ``None``. The regex PII provider ships a
    Tier-A payload from ``scripts/bench/run_pii_bench.py``; everything
    else is None until benchmarked."""
    payload = list_plugins(config=AppConfig())
    for category in ("ocr", "pii", "document_ai"):
        for p in payload[category]["providers"]:
            assert "accuracy" in p, f"{category}.{p['name']} missing accuracy"
    by_name = {p["name"]: p for p in payload["pii"]["providers"]}
    regex_accuracy = by_name["regex"]["accuracy"]
    assert regex_accuracy is not None
    assert regex_accuracy["tier"] == "A"
    assert regex_accuracy["metric_name"] == "f1"
    assert isinstance(regex_accuracy["headline"], (int, float))
    # Other PII providers have no benchmark yet.
    assert by_name["piiranha"]["accuracy"] is None
    assert by_name["roberta_ner"]["accuracy"] is None


def test_list_plugins_accuracy_payload_sanitised(monkeypatch) -> None:
    """A provider declaring accuracy_metrics with a known tier surfaces
    a normalised payload; unknown tiers are dropped (returns None)."""
    from care.pii.providers.regex_provider import RegexPIIProvider

    monkeypatch.setattr(
        RegexPIIProvider,
        "accuracy_metrics",
        {
            "tier": "A",
            "benchmark": "care-pii-bench-v1",
            "benchmark_version": "2026-05-01",
            "metric_name": "f1",
            "headline": 0.83,
            "per_entity": {"PHONE": 0.99, "VIN": 0.97},
            "notes": "Synthetic corpus; deterministic regex baseline.",
        },
        raising=False,
    )
    payload = list_plugins(config=AppConfig())
    regex = next(p for p in payload["pii"]["providers"] if p["name"] == "regex")
    assert regex["accuracy"] == {
        "tier": "A",
        "benchmark": "care-pii-bench-v1",
        "benchmark_version": "2026-05-01",
        "metric_name": "f1",
        "headline": 0.83,
        "per_entity": {"PHONE": 0.99, "VIN": 0.97},
        "notes": "Synthetic corpus; deterministic regex baseline.",
    }

    # Unknown tier -> entire payload dropped.
    monkeypatch.setattr(
        RegexPIIProvider,
        "accuracy_metrics",
        {"tier": "Z", "benchmark": "x", "headline": 0.9},
        raising=False,
    )
    payload = list_plugins(config=AppConfig())
    regex = next(p for p in payload["pii"]["providers"] if p["name"] == "regex")
    assert regex["accuracy"] is None


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


def test_list_plugins_model_files_present_accepts_onnx_only_dir(
    tmp_path: Path,
) -> None:
    """An OnnxTR-style ``model_dir`` containing ``*.onnx`` files but
    no HuggingFace ``config.json`` must report ``model_files_present
    = True``. Pre-fix the check insisted on ``config.json`` for any
    ``model_dir`` and rejected valid ONNX layouts."""
    onnx_dir = tmp_path / "onnxtr"
    onnx_dir.mkdir()
    (onnx_dir / "fast_base.onnx").write_bytes(b"\x00")
    (onnx_dir / "crnn_vgg16_bn.onnx").write_bytes(b"\x00")

    cfg = AppConfig(
        ocr=OCRSection(
            provider_chain=["mock_ocr"],
            providers={
                "onnxtr": {
                    "model_dir": str(onnx_dir),
                    "det_arch": "fast_base",
                    "reco_arch": "crnn_vgg16_bn",
                },
            },
        ),
    )
    payload = list_plugins(config=cfg)
    by_name = {p["name"]: p for p in payload["ocr"]["providers"]}
    assert by_name["onnxtr"]["model_files_present"] is True


def test_list_plugins_model_files_present_accepts_paddleocr_layout(
    tmp_path: Path,
) -> None:
    """PaddleOCR drops ``*.pdmodel`` / ``*.pdiparams`` files into its
    det/rec/cls dirs — no ``config.json`` either."""
    det = tmp_path / "det"
    rec = tmp_path / "rec"
    det.mkdir()
    rec.mkdir()
    (det / "inference.pdmodel").write_bytes(b"\x00")
    (det / "inference.pdiparams").write_bytes(b"\x00")
    (rec / "inference.pdmodel").write_bytes(b"\x00")
    (rec / "inference.pdiparams").write_bytes(b"\x00")

    cfg = AppConfig(
        ocr=OCRSection(
            provider_chain=["mock_ocr"],
            providers={
                "paddleocr": {
                    "det_model_dir": str(det),
                    "rec_model_dir": str(rec),
                },
            },
        ),
    )
    payload = list_plugins(config=cfg)
    by_name = {p["name"]: p for p in payload["ocr"]["providers"]}
    assert by_name["paddleocr"]["model_files_present"] is True


def test_list_plugins_model_files_present_accepts_tessdata(tmp_path: Path) -> None:
    """Tesseract uses ``tessdata_dir`` with ``*.traineddata`` files."""
    tessdata = tmp_path / "tessdata"
    tessdata.mkdir()
    (tessdata / "eng.traineddata").write_bytes(b"\x00")

    cfg = AppConfig(
        ocr=OCRSection(
            provider_chain=["mock_ocr"],
            providers={"tesseract": {"tessdata_dir": str(tessdata)}},
        ),
    )
    payload = list_plugins(config=cfg)
    by_name = {p["name"]: p for p in payload["ocr"]["providers"]}
    assert by_name["tesseract"]["model_files_present"] is True


def test_list_plugins_model_files_present_rejects_empty_dir(
    tmp_path: Path,
) -> None:
    """A ``model_dir`` that exists but is empty (no ``config.json``,
    no ``*.onnx``, no ``*.pdmodel``, no ``*.traineddata``) is still
    'no plausible weights' — must return False."""
    empty = tmp_path / "empty"
    empty.mkdir()

    cfg = AppConfig(
        pii=PIISection(
            provider_chain=["regex"],
            providers={"piiranha": {"model_dir": str(empty)}},
        )
    )
    payload = list_plugins(config=cfg)
    by_name = {p["name"]: p for p in payload["pii"]["providers"]}
    assert by_name["piiranha"]["model_files_present"] is False


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
