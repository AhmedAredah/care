from .builder import build_document_ir_from_native_text, build_document_ir_from_ocr
from .models import (
    AlternativeSource,
    Block,
    DocumentIR,
    Line,
    Page,
    Provenance,
    Region,
    Warning,
    Word,
)
from .serialization import from_json, to_json

__all__ = [
    "AlternativeSource",
    "Block",
    "DocumentIR",
    "Line",
    "Page",
    "Provenance",
    "Region",
    "Warning",
    "Word",
    "build_document_ir_from_native_text",
    "build_document_ir_from_ocr",
    "from_json",
    "to_json",
]
