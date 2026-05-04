"""Plugin registry behavior: registration, lookup, rejection of unknown names."""
from __future__ import annotations

import pytest

from care.core.errors import PluginNotFoundError
from care.document_ai import registry as vlm_registry
from care.document_ai.base import DocumentAIProvider
from care.ocr import registry as ocr_registry
from care.ocr.base import OCRProvider
from care.pii import registry as pii_registry
from care.pii.base import PIIDetectionProvider

# ---------- OCR ----------


def test_ocr_registry_knows_mock_noop_and_phase5_skeletons() -> None:
    reg = ocr_registry.get_registry()
    names = reg.names()
    assert "mock_ocr" in names
    assert "noop" in names
    # Phase 5 added real-OCR provider skeletons. They're disabled by default
    # in config.yaml and only load when local model files exist.
    assert "paddleocr" in names
    assert "tesseract" in names


def test_ocr_registry_rejects_genuinely_unknown_provider() -> None:
    reg = ocr_registry.get_registry()
    with pytest.raises(PluginNotFoundError):
        reg.get("totally_made_up_provider")


def test_ocr_registry_rejects_non_provider_class() -> None:
    reg = ocr_registry.get_registry()

    class NotAProvider:
        pass

    with pytest.raises(TypeError):
        reg.register("bogus", NotAProvider)  # type: ignore[arg-type]


# ---------- Document-AI / VLM ----------


def test_document_ai_registry_knows_mock_vlm_and_kosmos25() -> None:
    reg = vlm_registry.get_registry()
    names = reg.names()
    assert "mock_vlm" in names
    # Phase 5 skeleton — registered but disabled by default in config.
    assert "kosmos25" in names


def test_kosmos25_provider_class_is_disabled_by_default() -> None:
    """test_kosmos25_provider_disabled_by_default — class-level flag plus
    the default `config.yaml` keep Kosmos-2.5 off until an operator opts in."""
    reg = vlm_registry.get_registry()
    cls = reg.get("kosmos25")
    assert cls.enabled_by_default is False
    assert cls.requires_network is False
    assert cls.generative_model is True
    assert cls.hallucination_risk is True


# ---------- PII ----------


def test_pii_registry_knows_default_providers() -> None:
    reg = pii_registry.get_registry()
    names = reg.names()
    assert "mock_pii" in names
    assert "regex" in names
    # Phase 5 skeletons — registered but disabled by default in config.
    assert "presidio" in names
    assert "piiranha" in names


def test_piiranha_provider_class_is_disabled_by_default() -> None:
    """test_piiranha_plugin_disabled_by_default — the class-level flag plus
    the default `config.yaml` keep Piiranha off until an operator opts in."""
    reg = pii_registry.get_registry()
    cls = reg.get("piiranha")
    assert cls.enabled_by_default is False


# ---------- Provider ABC behaviour ----------


def test_ocr_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        OCRProvider()  # type: ignore[abstract]


def test_document_ai_provider_is_abstract() -> None:
    """test_document_ai_provider_interface — the ABC is not instantiable."""
    with pytest.raises(TypeError):
        DocumentAIProvider()  # type: ignore[abstract]


def test_pii_provider_is_abstract() -> None:
    with pytest.raises(TypeError):
        PIIDetectionProvider()  # type: ignore[abstract]
