"""Build DocumentIR from provider outputs.

Three construction paths:

- ``build_document_ir_from_ocr`` — every page from a traditional OCR
  provider.
- ``build_document_ir_from_native_text`` — every page from a PDF text
  layer.
- ``build_document_ir_from_pages`` — caller has already constructed
  per-page :class:`Page` objects with the right ``text_source`` set.
  Used by the mixed-source pipeline path that routes each page
  individually (some pages take the native route, others rasterize
  and OCR).

Reconciliation (merging native + OCR + VLM) is a later stage and is
not the responsibility of this module.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional, Union

from .. import __version__ as _CARE_VERSION
from ..ocr.result import OCRResult
from ..pdf.base import NativeTextWord
from .models import DocumentIR, Page, Provenance, Word


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_ocr_page(
    *,
    page_index: int,
    width: int,
    height: int,
    result: OCRResult,
) -> Page:
    """Construct a single OCR-sourced :class:`Page`.

    Used by the mixed-source pipeline path so the per-page routing
    code doesn't have to duplicate Word construction. The ``source``
    fields are populated identically to
    :func:`build_document_ir_from_ocr`.
    """
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
    return Page(
        page_index=page_index,
        width=width,
        height=height,
        text_source="ocr",
        words=words,
    )


def build_native_page(
    *,
    page_index: int,
    width: int,
    height: int,
    words: list[Union[NativeTextWord, str]],
) -> Page:
    """Construct a single native-text-sourced :class:`Page`.

    Mirrors :func:`build_document_ir_from_native_text` for one page.
    Native text comes from pypdfium2's textpage — the document
    author's own representation — so words inherit ``confidence=1.0``
    so the QA gate can reason uniformly across native and OCR pages.
    """
    provenance = Provenance(
        provider="native_pdf",
        provider_version="pypdfium2",
        provider_type="native_pdf",
    )
    out_words: list[Word] = []
    for j, item in enumerate(words):
        if isinstance(item, NativeTextWord):
            text = item.text
            bbox = item.bbox
            confidence = item.confidence
        else:
            text = str(item)
            bbox = None
            confidence = 1.0
        out_words.append(
            Word(
                id=f"p{page_index}_w{j:05d}",
                text=text,
                bbox=bbox,
                confidence=confidence,
                source="native_pdf",
                source_provider_type="native_pdf",
                source_provider_version="pypdfium2",
                provenance=provenance,
                can_map_to_image_coordinates=bbox is not None,
            )
        )
    return Page(
        page_index=page_index,
        width=width,
        height=height,
        text_source="native",
        words=out_words,
    )


def build_document_ir_from_pages(
    *,
    document_id: str,
    source_file_name: str,
    source_sha256: str,
    file_type: str,
    pages: list[Page],
    extra_provenance: Optional[list[Provenance]] = None,
) -> DocumentIR:
    """Wrap pre-built :class:`Page` objects in a :class:`DocumentIR`.

    Pages are sorted by ``page_index`` so callers don't have to care
    about the order they were appended in. The pipeline-level
    provenance entry is always added; ``extra_provenance`` (e.g., the
    backend's native-text provenance) is appended if supplied.
    """
    sorted_pages = sorted(pages, key=lambda p: p.page_index)
    provenance: list[Provenance] = [
        Provenance(
            provider="care.pipeline",
            provider_version=_CARE_VERSION,
            provider_type="pipeline",
        )
    ]
    if extra_provenance:
        provenance.extend(extra_provenance)
    return DocumentIR(
        document_id=document_id,
        source_file_name=source_file_name,
        source_sha256=source_sha256,
        file_type=file_type,
        created_at=_now_iso(),
        pages=sorted_pages,
        provenance=provenance,
    )


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
                provider_version=_CARE_VERSION,
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
                confidence = item.confidence
            else:
                text = str(item)
                bbox = None
                confidence = 1.0
            words.append(
                Word(
                    id=f"p{i}_w{j:05d}",
                    text=text,
                    bbox=bbox,
                    confidence=confidence,
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
