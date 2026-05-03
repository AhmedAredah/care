"""Template scoring helpers."""
from __future__ import annotations

from care.document_ir import (
    DocumentIR,
    Page,
    Provenance,
    Word,
)
from care.templates import TemplateSchema
from care.templates.scoring import score_template


def _doc(words_per_page: list[list[str]]) -> DocumentIR:
    pages = []
    prov = Provenance(provider="test", provider_version="0", provider_type="test")
    for page_index, tokens in enumerate(words_per_page):
        words = [
            Word(
                id=f"p{page_index}_w{i:05d}",
                text=tok,
                source="test",
                source_provider_type="test",
                provenance=prov,
            )
            for i, tok in enumerate(tokens)
        ]
        pages.append(Page(page_index=page_index, width=595, height=842, words=words))
    return DocumentIR(
        document_id="d",
        source_file_name="x.pdf",
        source_sha256="0" * 64,
        file_type="pdf",
        created_at="2026-05-01T00:00:00Z",
        pages=pages,
    )


def _template(**overrides) -> TemplateSchema:
    base = {
        "template_id": "t",
        "signature": {
            "anchor_text": ["Crash", "Report", "Narrative"],
            "form_number_regex": "EX-CR-[0-9]+",
        },
        "layout": {"page_count_min": 1, "page_count_max": 3},
    }
    base.update(overrides)
    return TemplateSchema.model_validate(base)


def test_perfect_match_yields_high_confidence() -> None:
    doc = _doc([["Example", "Crash", "Report", "EX-CR-99", "Narrative"]])
    score = score_template(_template(), doc)
    assert score.evidence.anchor_text_found == ("Crash", "Report", "Narrative")
    # Phase 9: form-number regex now searches the original (case-preserving)
    # haystack so logs show the verbatim match instead of a lowercased copy.
    assert score.evidence.form_number_match == "EX-CR-99"
    assert score.confidence >= 0.9


def test_missing_anchors_lowers_confidence() -> None:
    doc = _doc([["Some", "random", "EX-CR-1"]])
    score = score_template(_template(), doc)
    # No anchors found, but form regex matched.
    assert score.evidence.anchor_text_missing == ("Crash", "Report", "Narrative")
    # Without anchors and only form_score=1.0, weighted: 0.7*0 + 0.3*1.0 = 0.3
    assert score.confidence < 0.5


def test_page_count_out_of_range_zeros_score() -> None:
    doc = _doc([["Crash", "Report", "Narrative", "EX-CR-1"]] * 5)  # 5 pages
    score = score_template(_template(), doc)
    assert score.evidence.page_count_in_range is False
    assert score.confidence == 0.0


def test_low_ocr_confidence_dampens_score() -> None:
    doc = _doc([["Crash", "Report", "Narrative", "EX-CR-1"]])
    high = score_template(_template(), doc, ocr_confidence_average=0.95)
    low = score_template(_template(), doc, ocr_confidence_average=0.3)
    assert low.confidence < high.confidence
    assert low.confidence == round(high.confidence * 0.8, 4)
