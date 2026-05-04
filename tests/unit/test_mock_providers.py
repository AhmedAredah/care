"""Mock provider behavior tests."""
from __future__ import annotations

from care.document_ai.providers.mock_vlm_provider import MockVLMProvider
from care.document_ai.result import DocumentAIResult, MarkdownResult, SpatialTextResult
from care.ocr.providers.mock_ocr_provider import MockOCRProvider
from care.ocr.providers.noop_provider import NoopOCRProvider
from care.ocr.result import OCRResult
from care.pii.providers.mock_pii_provider import MockPIIProvider

# ---------- OCR ----------


def test_mock_ocr_provider_outputs_ocr_result() -> None:
    provider = MockOCRProvider()
    provider.load({})
    result = provider.process_page_image(image=None, page_context={})
    assert isinstance(result, OCRResult)
    assert result.provider_name == "mock_ocr"
    assert result.can_map_to_image_coordinates is True
    assert result.words and result.words[0].text == "MOCK"


def test_mock_ocr_manifest_marks_no_network_no_hallucination() -> None:
    manifest = MockOCRProvider().get_model_manifest()
    assert manifest["requires_network"] is False
    assert manifest["may_hallucinate"] is False
    assert manifest["safe_for_image_redaction"] is True


def test_noop_ocr_returns_empty_result() -> None:
    provider = NoopOCRProvider()
    provider.load({})
    result = provider.process_page_image(image=None, page_context={})
    assert isinstance(result, OCRResult)
    assert result.words == []
    assert result.can_map_to_image_coordinates is False


# ---------- Document-AI / VLM ----------


def test_mock_vlm_provider_outputs_document_ai_result() -> None:
    provider = MockVLMProvider()
    provider.load({})
    result = provider.process_page_image(image=None, page_context={}, task="spatial_ocr")
    assert isinstance(result, DocumentAIResult)
    assert result.provider_name == "mock_vlm"
    assert isinstance(result.spatial_text, SpatialTextResult)
    assert result.spatial_text is not None
    assert result.spatial_text.can_map_to_image_coordinates is True
    assert result.generative is True
    assert result.hallucination_risk is True


def test_mock_vlm_no_bboxes_mode_blocks_redaction_mapping() -> None:
    """Equivalent to test_vlm_without_bboxes_cannot_drive_image_redaction
    at the provider-output level: when the VLM cannot map to image
    coordinates, downstream code (Phase 4-5) must not use it for redaction."""
    provider = MockVLMProvider()
    provider.load({"mock_mode": "no_bboxes"})
    spatial = provider.image_to_spatial_text(image=None, page_context={})
    assert spatial.can_map_to_image_coordinates is False
    assert all(w.bbox is None for w in spatial.words)


def test_mock_vlm_markdown_has_sections() -> None:
    provider = MockVLMProvider()
    provider.load({})
    md = provider.image_to_markdown(image=None, page_context={})
    assert isinstance(md, MarkdownResult)
    assert md.markdown.startswith("# Narrative")
    assert md.sections and md.sections[0].heading == "Narrative"


def test_mock_vlm_manifest_marks_generative_and_hallucination() -> None:
    provider = MockVLMProvider()
    provider.load({})
    manifest = provider.get_model_manifest()
    assert manifest["generative"] is True
    assert manifest["may_hallucinate"] is True
    assert manifest["safe_for_image_redaction"] is False
    assert manifest["requires_network"] is False


# ---------- PII ----------


def test_mock_pii_provider_detects_synthetic_pii() -> None:
    provider = MockPIIProvider()
    provider.load({})
    text = "Call JOHN DOE at 555-123-4567 or jdoe@example.com. SSN 123-45-6789."
    entities = provider.detect_text(text)
    types = {e.entity_type for e in entities}
    assert "PHONE_NUMBER" in types
    assert "EMAIL" in types
    assert "SSN" in types
    assert "PERSON_NAME" in types
