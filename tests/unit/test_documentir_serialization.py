"""DocumentIR round-trip tests."""
from __future__ import annotations

from care.document_ir import (
    AlternativeSource,
    DocumentIR,
    Page,
    Provenance,
    Word,
    from_json,
    to_json,
)


def _sample_doc() -> DocumentIR:
    return DocumentIR(
        document_id="sha256-abc",
        source_file_name="example.pdf",
        source_sha256="abc",
        file_type="pdf",
        created_at="2026-05-01T00:00:00Z",
        pages=[
            Page(
                page_index=0,
                width=2550,
                height=3300,
                rotation=0,
                text_source="ocr",
                words=[
                    Word(
                        id="p0_w00001",
                        text="JOHN",
                        bbox=[100, 200, 180, 230],
                        confidence=0.97,
                        source="paddleocr",
                        source_provider_type="traditional_ocr",
                        source_provider_version="local",
                        alternative_sources=[
                            AlternativeSource(
                                provider="kosmos25",
                                text="JOHN",
                                bbox=[102, 198, 181, 232],
                            )
                        ],
                        provenance=Provenance(
                            provider="paddleocr",
                            provider_version="local",
                            provider_type="traditional_ocr",
                        ),
                        can_map_to_image_coordinates=True,
                    )
                ],
            )
        ],
    )


def test_documentir_round_trip() -> None:
    doc = _sample_doc()
    payload = to_json(doc)
    parsed = from_json(payload)
    assert parsed == doc


def test_documentir_word_provenance_preserved() -> None:
    doc = _sample_doc()
    word = doc.pages[0].words[0]
    assert word.source_provider_type == "traditional_ocr"
    assert word.alternative_sources[0].provider == "kosmos25"
    assert word.can_map_to_image_coordinates is True


def test_documentir_extra_keys_rejected() -> None:
    """DocumentIR is a strict schema: extra keys at the root are rejected."""
    import pytest
    from pydantic import ValidationError

    bad = {
        "document_id": "x",
        "source_file_name": "y",
        "source_sha256": "z",
        "file_type": "pdf",
        "created_at": "now",
        "pages": [],
        "unknown_field": True,
    }
    with pytest.raises(ValidationError):
        DocumentIR.model_validate(bad)
