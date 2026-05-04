"""Phase 9: builder serialization carries per-word confidence.

Native PDFs come from the document author's own text layer, so each
word's confidence is 1.0 by convention — the QA gate's
``require_review_for_low_ocr_confidence`` therefore reasons
uniformly across native and OCR pages instead of skipping native
docs entirely. The field is always present so the frontend can
branch on its value without inspecting the missing-key case.
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
            # Native text is treated as ground-truth; confidence=1.0.
            assert word["confidence"] == 1.0
            found_word_with_field = True
    assert found_word_with_field, "expected at least one word in the payload"
