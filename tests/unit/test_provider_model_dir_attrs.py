"""Each concrete provider declares MODEL_DIR_KEYS / WEIGHT_MARKERS.

Pre-refactor the API endpoint enumerated every supported config key
and weight format itself, so adding a new OCR backend was a
multi-layer change. Now each provider class owns its own filesystem
contract; this test pins those attributes so a config-key rename or
weight-format change is caught at test time, not when the GUI silently
reports model_files_present=False on an otherwise-working install.
"""
from __future__ import annotations

import pytest

from care.document_ai.providers.kosmos25_provider import Kosmos25Provider
from care.document_ai.providers.layoutlm_provider import LayoutLMProvider
from care.ocr.providers.mock_ocr_provider import MockOCRProvider
from care.ocr.providers.noop_provider import NoopOCRProvider
from care.ocr.providers.onnxtr_provider import OnnxTROCRProvider
from care.ocr.providers.paddleocr_provider import PaddleOCRProvider
from care.ocr.providers.tesseract_provider import TesseractProvider
from care.pii.providers.mock_pii_provider import MockPIIProvider
from care.pii.providers.openai_privacy_filter_provider import (
    OpenAIPrivacyFilterProvider,
)
from care.pii.providers.optional_piiranha_provider import PiiranhaPIIProvider
from care.pii.providers.presidio_provider import PresidioPIIProvider
from care.pii.providers.regex_provider import RegexPIIProvider
from care.pii.providers.roberta_ner_provider import RobertaNERProvider


@pytest.mark.parametrize(
    "cls,expected_keys,expected_markers",
    [
        # --- OCR ---
        (OnnxTROCRProvider, ("model_dir",), ("*.onnx",)),
        (
            PaddleOCRProvider,
            ("det_model_dir", "rec_model_dir", "cls_model_dir"),
            ("*.pdmodel", "*.pdiparams"),
        ),
        (TesseractProvider, ("tessdata_dir",), ("*.traineddata",)),
        # --- PII ---
        (PiiranhaPIIProvider, ("model_dir",), ("config.json",)),
        (PresidioPIIProvider, ("model_dir",), ("config.json",)),
        (RobertaNERProvider, ("model_dir",), ("config.json",)),
        (OpenAIPrivacyFilterProvider, ("model_dir",), ("config.json",)),
        # --- DocumentAI ---
        (Kosmos25Provider, ("model_dir", "processor_dir"), ("config.json",)),
        (LayoutLMProvider, ("model_dir", "processor_dir"), ("config.json",)),
    ],
)
def test_provider_declares_model_dir_attrs(cls, expected_keys, expected_markers) -> None:
    assert cls.MODEL_DIR_KEYS == expected_keys
    assert cls.WEIGHT_MARKERS == expected_markers


@pytest.mark.parametrize(
    "cls",
    [
        MockOCRProvider,
        NoopOCRProvider,
        MockPIIProvider,
        RegexPIIProvider,
    ],
)
def test_pure_python_providers_declare_no_model_dirs(cls) -> None:
    """Pure-Python providers (mocks, regex) inherit the empty defaults
    so :meth:`model_files_present` returns None — that's how the GUI
    learns this provider doesn't need a model dir at all."""
    assert cls.MODEL_DIR_KEYS == ()
    # WEIGHT_MARKERS may be empty too; it's irrelevant when MODEL_DIR_KEYS is.
    assert cls.model_files_present({}) is None
