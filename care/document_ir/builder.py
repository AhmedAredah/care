"""Build DocumentIR from provider outputs.

Phase 2 supports two construction paths:

- `build_document_ir_from_ocr`         — page_results from a traditional OCR provider
- `build_document_ir_from_native_text` — page text from a PDF text layer

Reconciliation (merging native + OCR + VLM) is Phase 5.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Union

from ..ocr.result import OCRResult
from ..pdf.base import NativeTextWord
from .models import DocumentIR, Page, Provenance, Word


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_document_ir_from_ocr(
    *,
    document_id: str,
    source_file_name: str,
    source_sha256: str,
    file_type: str,
    page_results: list[tuple[int, int, int, OCRResult]],
) -> DocumentIR:
    """Build a DocumentIR where every word's source is an OCR provider.

    `page_results` is a list of `(page_index, width, height, OCRResult)` tuples,
    one per rendered page.
    """
    pages: list[Page] = []
    for page_index, width, height, result in page_results:
        provenance = Provenance(
            provider=result.provider_name or "unknown_ocr",
            provider_version=result.provider_version or "unknown",
            provider_type="traditional_ocr",
        )
        words = [
            Word(
                id=f"p{page_index}_w{i:05d}",
                text=ocr_word.text,
                bbox=ocr_word.bbox,
                confidence=ocr_word.confidence,
                source=result.provider_name or "unknown_ocr",
                source_provider_type="traditional_ocr",
                source_provider_version=result.provider_version or "unknown",
                provenance=provenance,
                can_map_to_image_coordinates=result.can_map_to_image_coordinates,
            )
            for i, ocr_word in enumerate(result.words)
        ]
        pages.append(
            Page(
                page_index=page_index,
                width=width,
                height=height,
                text_source="ocr",
                words=words,
            )
        )

    return DocumentIR(
        document_id=document_id,
        source_file_name=source_file_name,
        source_sha256=source_sha256,
        file_type=file_type,
        created_at=_now_iso(),
        pages=pages,
        provenance=[
            Provenance(
                provider="care.pipeline",
                provider_version="0.1.0",
                provider_type="pipeline",
            )
        ],
    )


def build_document_ir_from_native_text(
    *,
    document_id: str,
    source_file_name: str,
    source_sha256: str,
    file_type: str,
    page_dimensions: list[tuple[int, int]],
    page_word_lists: list[list[Union[NativeTextWord, str]]],
) -> DocumentIR:
    """Build a DocumentIR from native PDF text-layer extraction.

    Each entry in `page_word_lists[i]` may be a :class:`NativeTextWord`
    (Phase 5+, carrying an image-space bbox) or a bare string (legacy).
    String entries get ``can_map_to_image_coordinates=False`` since they
    have no bbox; ``NativeTextWord`` entries get the flag set from the
    presence of their bbox.
    """
    provenance = Provenance(
        provider="native_pdf",
        provider_version="pypdfium2",
        provider_type="native_pdf",
    )
    pages: list[Page] = []
    for i, (width, height) in enumerate(page_dimensions):
        tokens: Iterable = page_word_lists[i] if i < len(page_word_lists) else []
        words: list[Word] = []
        for j, item in enumerate(tokens):
            if isinstance(item, NativeTextWord):
                text = item.text
                bbox = item.bbox
            else:
                text = str(item)
                bbox = None
            words.append(
                Word(
                    id=f"p{i}_w{j:05d}",
                    text=text,
                    bbox=bbox,
                    source="native_pdf",
                    source_provider_type="native_pdf",
                    source_provider_version="pypdfium2",
                    provenance=provenance,
                    can_map_to_image_coordinates=bbox is not None,
                )
            )
        pages.append(
            Page(
                page_index=i,
                width=width,
                height=height,
                text_source="native",
                words=words,
            )
        )

    return DocumentIR(
        document_id=document_id,
        source_file_name=source_file_name,
        source_sha256=source_sha256,
        file_type=file_type,
        created_at=_now_iso(),
        pages=pages,
        provenance=[provenance],
    )
