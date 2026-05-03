"""Phase 9: builder serialization carries per-word confidence.

For native PDFs (no OCR), confidence is None; the field is still
present so the frontend can branch on its absence without inspecting
the missing-key case.
"""
from __future__ import annotations

from pathlib import Path

from care.services.template_builder import (
    TemplateBuilderStore,
    session_to_dict,
)
from tests._fixtures import make_digital_pdf


def test_session_dict_words_include_confidence_field(tmp_path: Path) -> None:
    src = make_digital_pdf(tmp_path / "sample.pdf")
    store = TemplateBuilderStore(work_dir=tmp_path / "work")
    session = store.create_session(src)
    payload = session_to_dict(session)
    pages = payload["pages"]
    assert pages, "digital PDF must produce at least one page"
    found_word_with_field = False
    for page in pages:
        for word in page["words"]:
            assert "text" in word
            assert "bbox" in word
            assert "confidence" in word
            # Native text has no OCR confidence — field is present but None.
            assert word["confidence"] is None
            found_word_with_field = True
    assert found_word_with_field, "expected at least one word in the payload"
