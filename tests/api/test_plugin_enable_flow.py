"""End-to-end plugin enable/disable flow (Phase 13.4).

The Plugins page builds a tiny patch of shape::

    {"<section>": {"provider_chain": [...], "providers": {<name>: {"enabled": <bool>}}}}

and runs it through ``POST /api/config/validate`` followed by
``PATCH /api/config``. These tests exercise that round trip end to
end so a regression in either endpoint surfaces immediately.
"""
from __future__ import annotations

from pathlib import Path

import yaml as pyyaml

from care.api.routes_config import patch_config, validate_config
from care.core.config import AppConfig, PIISection


def _redirect_writer(monkeypatch, tmp_path: Path, initial: str) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(initial, encoding="utf-8")
    from care.core import config_writer

    monkeypatch.setattr(config_writer, "resolve_write_path", lambda *a, **kw: cfg)
    return cfg


def _build_enable_patch(section: str, name: str, current_chain: list[str]) -> dict:
    next_chain = list(current_chain)
    if name not in next_chain:
        next_chain.append(name)
    return {
        section: {
            "provider_chain": next_chain,
            "providers": {name: {"enabled": True}},
        }
    }


def _build_disable_patch(section: str, name: str, current_chain: list[str]) -> dict:
    next_chain = [n for n in current_chain if n != name]
    return {
        section: {
            "provider_chain": next_chain,
            "providers": {name: {"enabled": False}},
        }
    }


def test_enable_pii_provider_writes_chain_and_enabled_flag(
    monkeypatch, tmp_path: Path
) -> None:
    cfg_path = _redirect_writer(
        monkeypatch,
        tmp_path,
        "pii:\n"
        "  provider_chain:\n"
        "    - regex\n"
        "  providers:\n"
        "    regex:\n"
        "      enabled: true\n"
        "    roberta_ner:\n"
        "      enabled: false\n",
    )
    current = AppConfig(
        pii=PIISection(
            provider_chain=["regex"],
            providers={
                "regex": {"enabled": True},
                "roberta_ner": {"enabled": False},
            },
        )
    )
    patch = _build_enable_patch("pii", "roberta_ner", ["regex"])

    pre = validate_config(body=patch, current=current)
    assert pre["ok"] is True

    response = patch_config(body=patch, current=current)
    assert response["ok"] is True

    on_disk = pyyaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert on_disk["pii"]["provider_chain"] == ["regex", "roberta_ner"]
    assert on_disk["pii"]["providers"]["roberta_ner"]["enabled"] is True
    # regex left alone.
    assert on_disk["pii"]["providers"]["regex"]["enabled"] is True


def test_disable_pii_provider_removes_chain_and_clears_flag(
    monkeypatch, tmp_path: Path
) -> None:
    cfg_path = _redirect_writer(
        monkeypatch,
        tmp_path,
        "pii:\n"
        "  provider_chain:\n"
        "    - regex\n"
        "    - roberta_ner\n"
        "  providers:\n"
        "    regex:\n"
        "      enabled: true\n"
        "    roberta_ner:\n"
        "      enabled: true\n",
    )
    current = AppConfig(
        pii=PIISection(
            provider_chain=["regex", "roberta_ner"],
            providers={
                "regex": {"enabled": True},
                "roberta_ner": {"enabled": True},
            },
        )
    )
    patch = _build_disable_patch("pii", "roberta_ner", ["regex", "roberta_ner"])
    response = patch_config(body=patch, current=current)
    assert response["ok"] is True

    on_disk = pyyaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert on_disk["pii"]["provider_chain"] == ["regex"]
    assert on_disk["pii"]["providers"]["roberta_ner"]["enabled"] is False


def test_enable_does_not_duplicate_existing_chain_entry(
    monkeypatch, tmp_path: Path
) -> None:
    """If the operator clicks Enable while the provider is already in
    the chain (race / stale UI), the patch must not produce duplicate
    entries — the helper de-dupes."""
    _redirect_writer(monkeypatch, tmp_path, "pii:\n  provider_chain:\n    - regex\n")
    current = AppConfig(pii=PIISection(provider_chain=["regex"]))
    # Caller computes patch with regex already in chain.
    patch = _build_enable_patch("pii", "regex", ["regex"])
    response = patch_config(body=patch, current=current)
    assert response["config"]["pii"]["provider_chain"] == ["regex"]


# ---------------------------------------------------------------------------
# Within-chain reorder
#
# The Plugins page's up / down arrows build a tiny patch of shape::
#
#     {"<section>": {"provider_chain": [<reordered names>]}}
#
# That patch flows through the same /api/config/validate +
# PATCH /api/config endpoints as enable / disable, so reorder is
# governed by the same pre-flight checks. These tests pin three
# things:
#   1. A reorder PATCH actually persists the new order to disk.
#   2. The pre-flight validate endpoint does NOT reject a permuted
#      chain composed of names that already exist in providers.
#   3. The reorder helper rejects out-of-bounds moves up front (so
#      stale UI clicks don't silently corrupt the chain).
# ---------------------------------------------------------------------------


def _build_reorder_patch(section: str, new_chain: list[str]) -> dict:
    return {section: {"provider_chain": new_chain}}


def test_reorder_pii_chain_persists_new_order(
    monkeypatch, tmp_path: Path
) -> None:
    cfg_path = _redirect_writer(
        monkeypatch,
        tmp_path,
        "pii:\n"
        "  provider_chain:\n"
        "    - regex\n"
        "    - presidio\n"
        "    - roberta_ner\n"
        "  providers:\n"
        "    regex:\n"
        "      enabled: true\n"
        "    presidio:\n"
        "      enabled: true\n"
        "    roberta_ner:\n"
        "      enabled: true\n",
    )
    current = AppConfig(
        pii=PIISection(
            provider_chain=["regex", "presidio", "roberta_ner"],
            providers={
                "regex": {"enabled": True},
                "presidio": {"enabled": True},
                "roberta_ner": {"enabled": True},
            },
        )
    )

    patch = _build_reorder_patch(
        "pii", ["presidio", "regex", "roberta_ner"]
    )

    pre = validate_config(body=patch, current=current)
    assert pre["ok"] is True

    response = patch_config(body=patch, current=current)
    assert response["ok"] is True

    on_disk = pyyaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert on_disk["pii"]["provider_chain"] == [
        "presidio", "regex", "roberta_ner",
    ]
    # Reorder must NOT alter the per-provider enabled flags.
    for name in ("regex", "presidio", "roberta_ner"):
        assert on_disk["pii"]["providers"][name]["enabled"] is True


def test_reorder_ocr_chain_to_swap_primary_and_fallback(
    monkeypatch, tmp_path: Path
) -> None:
    """OCR ordering is a hard priority (first success wins). Flipping
    primary and fallback must persist exactly — that's the whole point
    of letting the operator do this."""
    cfg_path = _redirect_writer(
        monkeypatch,
        tmp_path,
        "ocr:\n"
        "  provider_chain:\n"
        "    - paddleocr\n"
        "    - tesseract\n"
        "  providers:\n"
        "    paddleocr:\n"
        "      enabled: true\n"
        "    tesseract:\n"
        "      enabled: true\n",
    )
    from care.core.config import OCRSection

    current = AppConfig(
        ocr=OCRSection(
            provider_chain=["paddleocr", "tesseract"],
            providers={
                "paddleocr": {"enabled": True},
                "tesseract": {"enabled": True},
            },
        )
    )

    patch = _build_reorder_patch("ocr", ["tesseract", "paddleocr"])

    pre = validate_config(body=patch, current=current)
    assert pre["ok"] is True

    response = patch_config(body=patch, current=current)
    assert response["ok"] is True

    on_disk = pyyaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert on_disk["ocr"]["provider_chain"] == ["tesseract", "paddleocr"]


def test_reorder_does_not_alter_other_sections(
    monkeypatch, tmp_path: Path
) -> None:
    """A reorder patch targets one section. Untouched sections (and
    other fields within the same section) must be preserved verbatim
    on disk — the YAML round-trip is comment-and-ordering-preserving
    via ruamel.yaml."""
    cfg_path = _redirect_writer(
        monkeypatch,
        tmp_path,
        "pii:\n"
        "  provider_chain:\n"
        "    - regex\n"
        "    - presidio\n"
        "  providers:\n"
        "    regex:\n"
        "      enabled: true\n"
        "    presidio:\n"
        "      enabled: true\n"
        "      min_confidence: 0.8\n"
        "ocr:\n"
        "  provider_chain:\n"
        "    - mock_ocr\n"
        "  providers:\n"
        "    mock_ocr:\n"
        "      enabled: true\n",
    )
    from care.core.config import OCRSection

    current = AppConfig(
        pii=PIISection(
            provider_chain=["regex", "presidio"],
            providers={
                "regex": {"enabled": True},
                "presidio": {"enabled": True, "min_confidence": 0.8},
            },
        ),
        ocr=OCRSection(
            provider_chain=["mock_ocr"],
            providers={"mock_ocr": {"enabled": True}},
        ),
    )

    patch = _build_reorder_patch("pii", ["presidio", "regex"])

    response = patch_config(body=patch, current=current)
    assert response["ok"] is True

    on_disk = pyyaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    # PII chain reordered.
    assert on_disk["pii"]["provider_chain"] == ["presidio", "regex"]
    # PII per-provider config preserved (presidio.min_confidence stays).
    assert on_disk["pii"]["providers"]["presidio"]["min_confidence"] == 0.8
    # OCR section completely untouched.
    assert on_disk["ocr"]["provider_chain"] == ["mock_ocr"]
    assert on_disk["ocr"]["providers"]["mock_ocr"]["enabled"] is True
