"""Heuristic + LayoutLM region suggester unit tests."""
from __future__ import annotations

from pathlib import Path

from care.document_ai.result import (
    CandidateRegion,
    RegionDetectionResult,
)
from care.services.region_suggester import suggest_regions_for_page
from care.services.template_builder import (
    BuilderPage,
    BuilderWord,
)


def _word(text: str, x0: float, y0: float, x1: float, y1: float) -> BuilderWord:
    return BuilderWord(text=text, bbox=[x0, y0, x1, y1])


def _page(words: list[BuilderWord]) -> BuilderPage:
    return BuilderPage(
        index=0,
        width=1000,
        height=1000,
        image_path=Path("/tmp/page_0.png"),
        words=words,
    )


def test_heuristic_picks_sparsest_band_for_diagram_and_densest_for_narrative() -> None:
    """Crash-report shape: top half mostly empty (diagram), bottom
    half text-dense (narrative). The suggester should propose the
    top as diagram and the bottom as narrative."""
    words: list[BuilderWord] = []
    # 30 words concentrated in y=600..900 (densest band among 4).
    for i in range(30):
        x = 50 + (i * 25) % 900
        y = 650 + (i % 5) * 30
        words.append(_word(f"w{i}", x, y, x + 20, y + 18))
    page = _page(words)
    sugs, flags = suggest_regions_for_page(page)
    assert flags == []  # heuristic emits no LayoutLM flags
    labels = {s.label for s in sugs}
    assert "diagram" in labels
    assert "narrative" in labels
    diagram = next(s for s in sugs if s.label == "diagram")
    narrative = next(s for s in sugs if s.label == "narrative")
    # Diagram band is somewhere in the top half (sparser).
    assert diagram.bbox_norm[1] < 0.5
    # Narrative band is in the bottom half (where the words are).
    assert narrative.bbox_norm[1] >= 0.5
    assert diagram.requires_review is True
    assert narrative.requires_review is True
    assert diagram.source == "heuristic"


def test_heuristic_empty_page_returns_default_diagram_suggestion() -> None:
    """An image-only page (zero native words) gets a single fallback
    diagram suggestion covering the upper portion. The operator can
    accept or reject; nothing auto-applies."""
    sugs, flags = suggest_regions_for_page(_page([]))
    assert flags == []
    assert len(sugs) == 1
    assert sugs[0].label == "diagram"
    assert sugs[0].source == "heuristic"
    assert sugs[0].requires_review is True


def test_layoutlm_path_converts_0_1000_to_0_1() -> None:
    """LayoutLM returns bboxes in 0-1000 integer space (per the
    Hugging Face Transformers docs). Our suggester converts to
    [0..1]. This test pins the conversion."""
    class StubLM:
        def detect_regions(self, image, page_context):
            return RegionDetectionResult(
                regions=[
                    CandidateRegion(
                        label="diagram",
                        bbox=[100, 200, 900, 500],
                        confidence=0.83,
                    ),
                    CandidateRegion(
                        label="narrative",
                        bbox=[50, 600, 950, 950],
                        confidence=0.71,
                    ),
                ],
                provider="layoutlm",
            )

    page = _page([])
    sugs, flags = suggest_regions_for_page(page, layoutlm_provider=StubLM())
    assert "LAYOUTLM_PLUGIN_USED" in flags
    assert "LAYOUTLM_REGION_SUGGESTION" in flags
    assert "LAYOUTLM_REQUIRES_REVIEW" in flags
    assert len(sugs) == 2
    assert sugs[0].bbox_norm == [0.1, 0.2, 0.9, 0.5]
    assert sugs[0].source == "layoutlm"
    assert sugs[0].requires_review is True


def test_layoutlm_failure_falls_back_to_heuristic() -> None:
    """If the plugin raises (e.g., model not loaded), the suggester
    swallows the exception and falls back to the heuristic. The
    builder UX never shows an error for an optional feature."""
    class BrokenLM:
        def detect_regions(self, image, page_context):
            raise RuntimeError("model not loaded")

    sugs, flags = suggest_regions_for_page(_page([]), layoutlm_provider=BrokenLM())
    # Heuristic ran instead.
    assert flags == []
    assert all(s.source == "heuristic" for s in sugs)


def test_layoutlm_unimplemented_falls_back_to_heuristic() -> None:
    class StubProvider:
        def detect_regions(self, image, page_context):
            raise NotImplementedError

    sugs, flags = suggest_regions_for_page(_page([]), layoutlm_provider=StubProvider())
    assert flags == []
    assert all(s.source == "heuristic" for s in sugs)


def test_layoutlm_drops_invalid_bboxes() -> None:
    """A degenerate/inverted bbox from the model must be dropped, not
    forwarded to the operator as a real suggestion."""
    class StubLM:
        def detect_regions(self, image, page_context):
            return RegionDetectionResult(
                regions=[
                    CandidateRegion(label="ok", bbox=[100, 100, 500, 500], confidence=0.5),
                    CandidateRegion(label="degenerate", bbox=[500, 500, 100, 100], confidence=0.9),
                    CandidateRegion(label="malformed", bbox=[0, 0, 0, 0], confidence=0.9),
                    CandidateRegion(label="missing_bbox", bbox=None, confidence=0.9),
                ],
                provider="layoutlm",
            )

    sugs, flags = suggest_regions_for_page(_page([]), layoutlm_provider=StubLM())
    assert "LAYOUTLM_PLUGIN_USED" in flags
    # Only the well-formed one survives.
    assert len(sugs) == 1
    assert sugs[0].label == "ok"
