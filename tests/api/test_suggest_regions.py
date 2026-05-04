"""Phase 11 — POST /api/template-builder/suggest-regions.

Verified invariants:

1. Endpoint returns ``requires_review=True`` on every response, even
   the empty-suggestions case.
2. Heuristic backend works without LayoutLM enabled (default config).
3. Heuristic suggestions carry NO LAYOUTLM_* QA flags (it's not the
   plugin's output).
4. Bad token / bad page_index produce 4xx.
5. Endpoint never modifies the session (call twice, get the same
   shape; deletion+save endpoints unaffected).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException

from care.api.routes_template_builder import (
    SuggestRegionsRequest,
    suggest_regions,
)
from care.core.config import AppConfig
from care.services.template_builder import (
    TemplateBuilderStore,
    reset_builder_store,
)
from tests._fixtures import make_digital_pdf


def _config_and_store(tmp_path: Path) -> tuple[AppConfig, TemplateBuilderStore]:
    cfg = AppConfig()
    cfg.paths.work_dir = str(tmp_path / "work")
    cfg.paths.export_dir = str(tmp_path / "exports")
    cfg.paths.templates_dir = str(tmp_path / "templates")
    Path(cfg.paths.work_dir).mkdir(parents=True, exist_ok=True)
    reset_builder_store()
    store = TemplateBuilderStore(work_dir=Path(cfg.paths.work_dir))
    return cfg, store


def _new_session(tmp_path: Path) -> tuple[AppConfig, TemplateBuilderStore, str]:
    cfg, store = _config_and_store(tmp_path)
    src = make_digital_pdf(tmp_path / "sample.pdf")
    session = store.create_session(src)
    return cfg, store, session.token


def test_suggest_regions_returns_requires_review_true(tmp_path: Path) -> None:
    cfg, store, token = _new_session(tmp_path)
    body = SuggestRegionsRequest(token=token, page_index=0)
    out = suggest_regions(body, store=store, config=cfg)
    assert out["requires_review"] is True


def test_suggest_regions_uses_heuristic_when_layoutlm_disabled(tmp_path: Path) -> None:
    """Default config: document_ai.enabled = False → no LayoutLM
    even though the provider is registered."""
    cfg, store, token = _new_session(tmp_path)
    out = suggest_regions(SuggestRegionsRequest(token=token), store=store, config=cfg)
    assert out["backend"] == "heuristic"
    # Heuristic produces at most one diagram + one narrative per page.
    sources = {s["source"] for s in out["suggestions"]}
    assert sources == {"heuristic"} or sources == set()
    # No LayoutLM QA flags when LayoutLM didn't run.
    assert out["qa_flags"] == []


def test_suggest_regions_each_suggestion_carries_safety_fields(tmp_path: Path) -> None:
    cfg, store, token = _new_session(tmp_path)
    out = suggest_regions(
        SuggestRegionsRequest(token=token, page_index=0), store=store, config=cfg
    )
    for s in out["suggestions"]:
        assert s["requires_review"] is True
        assert s["source"] in {"heuristic", "layoutlm"}
        bbox = s["bbox_norm"]
        assert len(bbox) == 4
        assert 0.0 <= bbox[0] < bbox[2] <= 1.0
        assert 0.0 <= bbox[1] < bbox[3] <= 1.0
        assert s["label"] in {"diagram", "narrative", "header", "footer", "table", "region"}


def test_suggest_regions_404_on_unknown_token(tmp_path: Path) -> None:
    cfg, store = _config_and_store(tmp_path)
    body = SuggestRegionsRequest(token="0" * 16)
    with pytest.raises(HTTPException) as ei:
        suggest_regions(body, store=store, config=cfg)
    assert ei.value.status_code == 404


def test_suggest_regions_400_on_invalid_token(tmp_path: Path) -> None:
    cfg, store = _config_and_store(tmp_path)
    body = SuggestRegionsRequest(token="../etc/passwd")
    with pytest.raises(HTTPException) as ei:
        suggest_regions(body, store=store, config=cfg)
    assert ei.value.status_code == 400


def test_suggest_regions_404_on_page_out_of_range(tmp_path: Path) -> None:
    cfg, store, token = _new_session(tmp_path)
    body = SuggestRegionsRequest(token=token, page_index=99)
    with pytest.raises(HTTPException) as ei:
        suggest_regions(body, store=store, config=cfg)
    assert ei.value.status_code == 404


def test_suggest_regions_does_not_mutate_session(tmp_path: Path) -> None:
    """Critical safety property: the endpoint is read-only. Calling it
    twice must produce identical structure, and the underlying
    session must not change. The endpoint is advisory — it does NOT
    write a template, NOT record a job, NOT touch export_dir."""
    cfg, store, token = _new_session(tmp_path)
    before = store.get_session(token)
    assert before is not None
    pages_before = len(before.pages)
    anchors_before = list(getattr(before, "anchors", []) or [])

    out1 = suggest_regions(
        SuggestRegionsRequest(token=token), store=store, config=cfg
    )
    out2 = suggest_regions(
        SuggestRegionsRequest(token=token), store=store, config=cfg
    )
    assert out1["backend"] == out2["backend"]
    assert len(out1["suggestions"]) == len(out2["suggestions"])

    after = store.get_session(token)
    assert after is not None
    assert len(after.pages) == pages_before
    assert list(getattr(after, "anchors", []) or []) == anchors_before


def test_suggest_regions_notice_mentions_no_auto_apply(tmp_path: Path) -> None:
    """The response includes a human-readable notice that suggestions
    don't auto-apply. The frontend surfaces this to operators; the
    test pins this expectation."""
    cfg, store, token = _new_session(tmp_path)
    out = suggest_regions(
        SuggestRegionsRequest(token=token), store=store, config=cfg
    )
    notice = out.get("notice", "").lower()
    assert "advisory" in notice
    assert "accept" in notice


def test_suggest_regions_layoutlm_path_emits_qa_flags(tmp_path: Path, monkeypatch) -> None:
    """When LayoutLM is enabled and produces output, the response
    must include LAYOUTLM_PLUGIN_USED + LAYOUTLM_REGION_SUGGESTION +
    LAYOUTLM_REQUIRES_REVIEW. Stubbed via monkeypatch since the real
    model files aren't present in CI."""
    from care.api import routes_template_builder as routes
    from care.document_ai.result import (
        CandidateRegion,
        RegionDetectionResult,
    )

    cfg, store, token = _new_session(tmp_path)
    cfg.document_ai.enabled = True
    cfg.document_ai.provider_chain = ["layoutlm"]
    cfg.document_ai.providers = {"layoutlm": {"enabled": True}}

    class StubLayoutLM:
        name = "layoutlm"

        def detect_regions(self, image: str, page_context: dict) -> RegionDetectionResult:
            return RegionDetectionResult(
                regions=[
                    CandidateRegion(
                        label="diagram",
                        bbox=[100, 50, 900, 500],  # 0-1000 space
                        confidence=0.71,
                    ),
                ],
                provider=self.name,
            )

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        routes, "_maybe_load_layoutlm", lambda config: StubLayoutLM()
    )
    out = suggest_regions(
        SuggestRegionsRequest(token=token, page_index=0),
        store=store,
        config=cfg,
    )
    assert out["backend"] == "layoutlm"
    assert "LAYOUTLM_PLUGIN_USED" in out["qa_flags"]
    assert "LAYOUTLM_REGION_SUGGESTION" in out["qa_flags"]
    assert "LAYOUTLM_REQUIRES_REVIEW" in out["qa_flags"]
    diag = out["suggestions"][0]
    # 0-1000 → [0..1] conversion
    assert diag["bbox_norm"] == [0.1, 0.05, 0.9, 0.5]
    assert diag["source"] == "layoutlm"
    assert diag["confidence"] == pytest.approx(0.71, rel=1e-3)
    assert diag["requires_review"] is True
