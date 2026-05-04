"""Phase 9 VLM second-opinion diagram check.

Critical invariants verified here:

1. The check is **flag-only** — DIAGRAM_VLM_DISAGREES is NOT in
   BLOCKING_QA_FLAGS, so the QA gate does not promote it to a block.
2. A VLM exception or NotImplementedError is silently absorbed (the
   check must never crash the pipeline).
3. When the VLM description contains any keyword, the function
   returns None (no flag).
4. When the description is missing every keyword, the function
   returns DIAGRAM_VLM_DISAGREES.
5. When the image_path doesn't exist, the function returns None
   (defensive — extractor should never call it with a missing path,
   but we don't want to crash if it does).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from care.core.constants import BLOCKING_QA_FLAGS
from care.document_ai.base import (
    DocumentAIProvider,
    DocumentAIResult,
    MarkdownResult,
    ProviderHealth,
)
from care.extraction.vlm_diagram_review import vlm_disagrees_with_diagram


def _png(path: Path) -> Path:
    """Minimal valid PNG so Path.exists() returns True."""
    from PIL import Image

    Image.new("RGB", (4, 4), "white").save(path, format="PNG")
    return path


class _StubVLM(DocumentAIProvider):
    name = "stub_vlm"
    version = "0"
    provider_type = "document_ai"
    requires_network = False
    license = "internal"

    def __init__(self, *, markdown: str | None = None, raise_md: bool = False) -> None:
        self._md = markdown
        self._raise = raise_md

    def load(self, config: dict[str, Any]) -> None:  # noqa: D401
        return None

    def process_page_image(
        self, image: Any, page_context: dict[str, Any], task: str
    ) -> DocumentAIResult:
        raise NotImplementedError

    def image_to_markdown(
        self, image: Any, page_context: dict[str, Any]
    ) -> MarkdownResult:
        if self._raise:
            raise RuntimeError("simulated VLM failure")
        return MarkdownResult(markdown=self._md or "", provider=self.name)

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(ok=True, details="stub")

    def get_model_manifest(self) -> dict[str, Any]:
        return {"name": "stub", "version": "0"}


def test_disagree_flag_not_blocking() -> None:
    """The whole point of this feature: it MUST NOT block export."""
    assert "DIAGRAM_VLM_DISAGREES" not in BLOCKING_QA_FLAGS


def test_returns_flag_when_description_lacks_keywords(tmp_path: Path) -> None:
    img = _png(tmp_path / "diagram.png")
    provider = _StubVLM(markdown="A signature block, name and badge number.")
    out = vlm_disagrees_with_diagram(
        img,
        providers=[provider],
        keywords=["diagram", "vehicle", "intersection"],
        page_index=0,
    )
    assert out == "DIAGRAM_VLM_DISAGREES"


def test_returns_none_when_description_matches_keyword(tmp_path: Path) -> None:
    img = _png(tmp_path / "diagram.png")
    provider = _StubVLM(
        markdown="Crash diagram showing two vehicles at an intersection."
    )
    out = vlm_disagrees_with_diagram(
        img,
        providers=[provider],
        keywords=["diagram", "vehicle"],
        page_index=0,
    )
    assert out is None


def test_returns_none_on_provider_exception(tmp_path: Path) -> None:
    img = _png(tmp_path / "diagram.png")
    provider = _StubVLM(raise_md=True)
    out = vlm_disagrees_with_diagram(
        img,
        providers=[provider],
        keywords=["diagram"],
        page_index=0,
    )
    assert out is None  # exception absorbed; no flag emitted


def test_returns_none_on_missing_image_path(tmp_path: Path) -> None:
    provider = _StubVLM(markdown="anything")
    out = vlm_disagrees_with_diagram(
        tmp_path / "ghost.png",
        providers=[provider],
        keywords=["diagram"],
        page_index=0,
    )
    assert out is None


def test_returns_none_with_empty_keywords(tmp_path: Path) -> None:
    img = _png(tmp_path / "diagram.png")
    provider = _StubVLM(markdown="something unrelated")
    out = vlm_disagrees_with_diagram(
        img, providers=[provider], keywords=[], page_index=0
    )
    assert out is None  # nothing to compare against


def test_returns_none_with_no_providers(tmp_path: Path) -> None:
    img = _png(tmp_path / "diagram.png")
    out = vlm_disagrees_with_diagram(
        img, providers=[], keywords=["diagram"], page_index=0
    )
    assert out is None
