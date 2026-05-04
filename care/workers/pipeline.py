"""Pipeline orchestration (Phase 5).

Stages now implemented:

  1. Ingestion
  2. File inspection
  3. Rendering (when needed for OCR or diagram extraction)
  4. Native PDF text extraction (with image-space char/word bboxes)
  5. Traditional OCR — provider-chain fallback
  6. Optional VLM / document-AI parsing (when enabled)
  7. OCR / VLM reconciliation
  -- DocumentIR build --
  8. Template detection
  9. Diagram extraction
 10. Narrative extraction
 11. PII detection (provider chain) — page text + extracted narrative
 12. Redaction + public export (gated on QA)
 13. QA / fail-closed gate
 14. Public export writer

The exporter refuses to write anything when ``qa.export_blocked`` is True.
VLM-only text without bboxes is recorded as warnings only — it never
drives image redaction or final narrative export.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..core.config import AppConfig, load_config
from ..core.errors import ConfigError
from ..core.paths import work_dir as _work_dir
from ..document_ai.base import DocumentAIProvider
from ..document_ai.registry import get_registry as get_vlm_registry
from ..document_ir import DocumentIR
from ..document_ir.builder import (
    build_document_ir_from_native_text,
    build_document_ir_from_ocr,
    build_document_ir_from_pages,
    build_native_page,
    build_ocr_page,
)
from ..document_ir.models import (
    AlternativeSource,
    Page as IRPage,
    Provenance,
    Warning as IRWarning,
    Word as IRWord,
)
from ..document_ir.reconcile import (
    AlternativeSourceDoc,
    ReconciliationResult,
    reconcile_with_alternatives,
)
from ..export import ExportResult, export_artifact
from ..extraction import (
    DiagramExtraction,
    NarrativeExtraction,
    extract_diagram,
    extract_narrative,
)
from ..extraction.vlm_diagram_review import vlm_disagrees_with_diagram
from ..ingestion.file_manifest import FileEntry, build_file_manifest
from ..ingestion.scanner import scan_directory
from ..ocr.base import OCRProvider
from ..ocr.registry import get_registry as get_ocr_registry
from ..ocr.result import OCRResult
from ..pdf.base import FileInspection, NativeTextWord, PDFImageBackend, RenderedPage
from ..pdf.pypdfium2_backend import PypdfiumPDFImageBackend
from ..pii.base import PIIDetectionProvider
from ..pii.entities import PIIEntity
from ..pii.merge import merge_entities
from ..pii.registry import get_registry as get_pii_registry
from ..redaction import attach_bbox_to_pii_entities
from ..review import QAReport, build_qa_report
from ..review.confidence import average_word_confidence
from ..templates import (
    TemplateRegistry,
    detect_template,
    load_templates_from_directory,
)
from ..templates.detector import TemplateMatch

_log = logging.getLogger(__name__)

DEFAULT_RENDER_DPI = 200


@dataclass
class ReportArtifact:
    file_entry: FileEntry
    inspection: FileInspection
    document_ir: DocumentIR
    text_source: str  # "native" | "ocr" | "mixed"
    template_match: TemplateMatch
    diagram: Optional[DiagramExtraction]
    narrative: Optional[NarrativeExtraction]
    qa: QAReport
    pii_entities_pages: list[PIIEntity] = field(default_factory=list)
    pii_entities_narrative: list[PIIEntity] = field(default_factory=list)
    ocr_provider_used: Optional[str] = None
    vlm_warnings: list[IRWarning] = field(default_factory=list)
    export_result: Optional[ExportResult] = None
    export_blocked: bool = True
    blocking_reasons: list[str] = field(default_factory=list)
    work_dir: Optional[str] = None


@dataclass
class PipelineRunResult:
    config: AppConfig
    file_entries: list[FileEntry]
    artifacts: list[ReportArtifact]
    template_registry: TemplateRegistry
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Provider instantiation
# ---------------------------------------------------------------------------


def _instantiate_ocr_chain(cfg: AppConfig) -> list[OCRProvider]:
    """Load every provider in `cfg.ocr.provider_chain` whose `enabled` is not
    explicitly false. Returns the list in chain order. Raises if none load."""
    chain = cfg.ocr.provider_chain
    if not chain:
        raise ConfigError("ocr.provider_chain must declare at least one provider")

    registry = get_ocr_registry()
    providers: list[OCRProvider] = []
    errors: list[str] = []
    for name in chain:
        provider_cfg = cfg.ocr.providers.get(name, {})
        if provider_cfg.get("enabled") is False:
            continue
        try:
            cls = registry.get(name)
            provider = cls()
            provider.load(provider_cfg)
            providers.append(provider)
        except Exception as exc:  # noqa: BLE001 — surface every chain failure
            errors.append(f"{name}: {exc}")
    if not providers:
        raise ConfigError(
            f"No OCR provider in chain {chain} could be loaded. Errors: {errors}"
        )
    return providers


def _instantiate_pii_chain(cfg: AppConfig) -> list[PIIDetectionProvider]:
    providers: list[PIIDetectionProvider] = []
    registry = get_pii_registry()
    for name in cfg.pii.provider_chain:
        provider_cfg = cfg.pii.providers.get(name, {})
        if provider_cfg.get("enabled") is False:
            continue
        cls = registry.get(name)
        provider = cls()
        provider.load(provider_cfg)
        providers.append(provider)
    return providers


def _instantiate_vlm_chain(cfg: AppConfig) -> list[DocumentAIProvider]:
    if not cfg.document_ai.enabled:
        return []
    chain = cfg.document_ai.provider_chain
    if not chain:
        return []
    registry = get_vlm_registry()
    providers: list[DocumentAIProvider] = []
    for name in chain:
        provider_cfg = cfg.document_ai.providers.get(name, {})
        if provider_cfg.get("enabled") is False:
            continue
        cls = registry.get(name)
        provider = cls()
        provider.load(provider_cfg)
        providers.append(provider)
    return providers


def _build_template_registry(cfg: AppConfig) -> TemplateRegistry:
    return TemplateRegistry(load_templates_from_directory(Path(cfg.paths.templates_dir)))


# ---------------------------------------------------------------------------
# OCR chain fallback
# ---------------------------------------------------------------------------


def _ocr_with_chain(
    image_path: str,
    page_context: dict,
    providers: list[OCRProvider],
) -> tuple[OCRResult, str]:
    """Run providers in order; return the first successful result."""
    last_err: Exception | None = None
    for provider in providers:
        try:
            result = provider.process_page_image(image=image_path, page_context=page_context)
            return result, provider.name
        except Exception as exc:  # noqa: BLE001
            _log.warning("OCR provider %s failed: %s; trying next.", provider.name, exc)
            last_err = exc
    raise RuntimeError(
        f"All OCR providers in chain failed; last error: {last_err}"
    )


# ---------------------------------------------------------------------------
# VLM alternative DocumentIR
# ---------------------------------------------------------------------------


def _build_vlm_alternative_doc(
    *,
    document_id: str,
    entry: FileEntry,
    rendered: list[RenderedPage],
    provider: DocumentAIProvider,
) -> DocumentIR:
    """Run the VLM's spatial-OCR task on each rendered page and wrap the
    output in a minimal DocumentIR-shaped alternative source."""
    pages: list[IRPage] = []
    provenance = Provenance(
        provider=provider.name,
        provider_version=provider.version,
        provider_type=provider.provider_type,
    )
    for r in rendered:
        try:
            spatial = provider.image_to_spatial_text(
                image=str(r.image_path),
                page_context={"page_index": r.page_index, "dpi": r.dpi},
            )
        except NotImplementedError:
            continue
        page_words: list[IRWord] = []
        for j, sw in enumerate(spatial.words):
            page_words.append(
                IRWord(
                    id=f"p{r.page_index}_w{j:05d}",
                    text=sw.text,
                    bbox=list(sw.bbox) if sw.bbox else None,
                    confidence=sw.confidence,
                    source=provider.name,
                    source_provider_type=provider.provider_type,
                    source_provider_version=provider.version,
                    provenance=provenance,
                    can_map_to_image_coordinates=spatial.can_map_to_image_coordinates
                    and sw.bbox is not None,
                )
            )
        pages.append(
            IRPage(
                page_index=r.page_index,
                width=r.width,
                height=r.height,
                text_source="vlm_spatial",
                words=page_words,
            )
        )
    return DocumentIR(
        document_id=document_id + "::vlm",
        source_file_name=entry.name,
        source_sha256=entry.sha256,
        file_type=entry.file_type,
        created_at="reconcile",
        pages=pages,
        provenance=[provenance],
    )


# ---------------------------------------------------------------------------
# PII detection
# ---------------------------------------------------------------------------


def _run_pii_chain(
    document_ir: DocumentIR,
    narrative: Optional[NarrativeExtraction],
    providers: list[PIIDetectionProvider],
) -> tuple[list[PIIEntity], list[PIIEntity]]:
    page_entities: list[PIIEntity] = []
    narrative_entities: list[PIIEntity] = []

    for provider in providers:
        for page in document_ir.pages:
            page_text = " ".join(w.text for w in page.words)
            entities = provider.detect_text(
                page_text,
                context={"scope": "page", "page_index": page.page_index},
            )
            for e in entities:
                e.page_index = page.page_index
            page_entities.extend(entities)

        if narrative is not None and narrative.text:
            entities = provider.detect_text(
                narrative.text,
                context={"scope": "narrative", "page_index": narrative.page_index},
            )
            for e in entities:
                e.page_index = narrative.page_index
            narrative_entities.extend(entities)

    page_entities = merge_entities(page_entities)
    narrative_entities = merge_entities(narrative_entities)

    for page in document_ir.pages:
        page_scope = [e for e in page_entities if e.page_index == page.page_index]
        attach_bbox_to_pii_entities(page, page_scope)

    return page_entities, narrative_entities


# ---------------------------------------------------------------------------
# Per-file processing
# ---------------------------------------------------------------------------


def _process_one(
    entry: FileEntry,
    backend: PDFImageBackend,
    ocr_providers: list[OCRProvider],
    vlm_providers: list[DocumentAIProvider],
    pii_providers: list[PIIDetectionProvider],
    work_root: Path,
    template_registry: TemplateRegistry,
    cfg: AppConfig,
) -> ReportArtifact:
    path = Path(entry.path)
    inspection = backend.inspect_file(path)
    document_id = f"sha256-{entry.sha256[:16]}"
    doc_work = work_root / entry.sha256

    rendered: list[RenderedPage] = []
    ocr_provider_used: Optional[str] = None

    # Per-page text-source routing. The inspection populates
    # ``page_has_text`` so we can take the native path for pages with
    # an extractable text layer and rasterize-and-OCR only the image-
    # only pages within the same PDF. Pure-native and pure-OCR docs
    # collapse to the original two paths automatically (every page
    # falls into the same bucket).
    is_pdf = entry.file_type == "pdf"
    page_has_text = list(inspection.page_has_text)
    # Defensive fallback: an inspection synthesised without per-page
    # info (legacy callers, image inputs constructed elsewhere) has an
    # empty list. Fill it from the document-level flag so routing
    # stays correct.
    if not page_has_text or len(page_has_text) != inspection.page_count:
        page_has_text = [bool(inspection.has_text_layer)] * inspection.page_count

    if is_pdf and any(page_has_text):
        scale = DEFAULT_RENDER_DPI / 72.0
        page_dimensions_image = [
            (int(round(w_pt * scale)), int(round(h_pt * scale)))
            for w_pt, h_pt in inspection.page_dimensions
        ]

        # Native words come back per-page already, so this is just a bucket fill.
        native = backend.extract_text_layer(path, dpi=DEFAULT_RENDER_DPI)
        page_word_lists: list[list[NativeTextWord]] = [
            [] for _ in page_dimensions_image
        ]
        for word in native.words:
            if 0 <= word.page_index < len(page_word_lists):
                page_word_lists[word.page_index].append(word)

        # Rasterize only the pages that actually need OCR.
        ocr_page_indices = [i for i, has in enumerate(page_has_text) if not has]
        ocr_rendered: list[RenderedPage] = []
        if ocr_page_indices:
            ocr_rendered = backend.render_pages(
                path,
                doc_work,
                dpi=DEFAULT_RENDER_DPI,
                page_indices=ocr_page_indices,
            )
            rendered.extend(ocr_rendered)

        rendered_by_index = {r.page_index: r for r in ocr_rendered}
        composed_pages: list[IRPage] = []
        for i, (w_img, h_img) in enumerate(page_dimensions_image):
            if page_has_text[i]:
                composed_pages.append(
                    build_native_page(
                        page_index=i,
                        width=w_img,
                        height=h_img,
                        words=list(page_word_lists[i]),
                    )
                )
            else:
                r = rendered_by_index.get(i)
                if r is None:
                    # Defensive: should not happen — we asked for this
                    # index above. Skip rather than crash the doc.
                    composed_pages.append(
                        build_ocr_page(
                            page_index=i,
                            width=w_img,
                            height=h_img,
                            result=OCRResult(),
                        )
                    )
                    continue
                ocr_result, provider_name = _ocr_with_chain(
                    str(r.image_path),
                    {"page_index": r.page_index, "dpi": r.dpi},
                    ocr_providers,
                )
                ocr_provider_used = provider_name
                composed_pages.append(
                    build_ocr_page(
                        page_index=r.page_index,
                        width=r.width,
                        height=r.height,
                        result=ocr_result,
                    )
                )

        document_ir = build_document_ir_from_pages(
            document_id=document_id,
            source_file_name=entry.name,
            source_sha256=entry.sha256,
            file_type=entry.file_type,
            pages=composed_pages,
            extra_provenance=[
                Provenance(
                    provider="native_pdf",
                    provider_version="pypdfium2",
                    provider_type="native_pdf",
                )
            ],
        )
        # Document-level summary: stays "native" when every page took
        # the native route, "ocr" if every page was rasterized, and
        # "mixed" when both happened.
        if all(page_has_text):
            text_source = "native"
        elif not any(page_has_text):
            text_source = "ocr"
        else:
            text_source = "mixed"
    else:
        rendered = backend.render_pages(path, doc_work, dpi=DEFAULT_RENDER_DPI)
        page_results = []
        for r in rendered:
            ocr_result, provider_name = _ocr_with_chain(
                str(r.image_path),
                {"page_index": r.page_index, "dpi": r.dpi},
                ocr_providers,
            )
            ocr_provider_used = provider_name
            page_results.append((r.page_index, r.width, r.height, ocr_result))
        document_ir = build_document_ir_from_ocr(
            document_id=document_id,
            source_file_name=entry.name,
            source_sha256=entry.sha256,
            file_type=entry.file_type,
            page_results=page_results,
        )
        text_source = "ocr"

    # ---- Phase 5: optional VLM/document-AI alternative DocumentIR -----

    vlm_warnings: list[IRWarning] = []
    if vlm_providers:
        if not rendered:
            rendered = backend.render_pages(path, doc_work, dpi=DEFAULT_RENDER_DPI)
        alts: list[AlternativeSourceDoc] = []
        for vlm in vlm_providers:
            try:
                alt_doc = _build_vlm_alternative_doc(
                    document_id=document_id,
                    entry=entry,
                    rendered=rendered,
                    provider=vlm,
                )
            except Exception as exc:  # noqa: BLE001 — VLM failure must not crash pipeline
                _log.warning("VLM provider %s failed: %s", vlm.name, exc)
                continue
            alts.append(
                AlternativeSourceDoc(
                    document_ir=alt_doc,
                    provider_name=vlm.name,
                    generative=vlm.generative_model,
                    hallucination_risk=vlm.hallucination_risk,
                )
            )
        if alts:
            recon: ReconciliationResult = reconcile_with_alternatives(document_ir, alts)
            document_ir = recon.document_ir
            vlm_warnings = recon.warnings

    # ---- Phase 3: template detection -----------------------------------

    # Mixed docs have OCR-sourced pages whose confidence still matters
    # for the QA gate; native-only docs report None as before.
    avg_confidence = (
        average_word_confidence(document_ir)
        if text_source in ("ocr", "mixed")
        else None
    )
    template_match = detect_template(
        document_ir,
        template_registry,
        confidence_threshold=cfg.template_detection.confidence_threshold,
        ocr_confidence_average=avg_confidence,
    )

    # ---- Phase 3: extraction -------------------------------------------

    diagram: Optional[DiagramExtraction] = None
    narrative: Optional[NarrativeExtraction] = None

    if template_registry.has(template_match.template_id):
        template = template_registry.get(template_match.template_id)
        if not rendered:
            rendered = backend.render_pages(path, doc_work, dpi=DEFAULT_RENDER_DPI)
        source_image_paths: dict[int, Path] = {
            r.page_index: r.image_path for r in rendered
        }
        diagram = extract_diagram(
            template,
            document_ir,
            work_dir=doc_work,
            source_image_paths=source_image_paths,
        )
        narrative = extract_narrative(template, document_ir)

        # Phase 9: optional VLM second-opinion on the diagram crop. The
        # check is informational — it can add a QA flag but never
        # blocks export and never replaces the template-driven crop.
        if (
            cfg.extraction.vlm_diagram_review_enabled
            and vlm_providers
            and diagram is not None
            and diagram.image_path
        ):
            disagree_flag = vlm_disagrees_with_diagram(
                diagram.image_path,
                providers=vlm_providers,
                keywords=cfg.extraction.vlm_diagram_review_keywords,
                page_index=diagram.page_index,
            )
            if disagree_flag:
                diagram.warnings.append(disagree_flag)
    else:
        source_image_paths = {r.page_index: r.image_path for r in rendered}

    # ---- Phase 4: PII detection ----------------------------------------

    page_pii: list[PIIEntity] = []
    narrative_pii: list[PIIEntity] = []
    if pii_providers:
        page_pii, narrative_pii = _run_pii_chain(document_ir, narrative, pii_providers)

    # ---- QA gate ------------------------------------------------------

    qa = build_qa_report(
        template_match,
        diagram,
        narrative,
        pii_entities_pages=page_pii,
        vlm_warnings=vlm_warnings,
        template_confidence_threshold=cfg.template_detection.confidence_threshold,
    )

    # ---- Phase 4: export (only when QA allows) -------------------------

    export_result: Optional[ExportResult] = None
    if not qa.export_blocked:
        export_result = export_artifact(
            artifact=_artifact_view(
                entry, inspection, document_ir, text_source,
                template_match, diagram, narrative, qa,
                page_pii, narrative_pii, doc_work,
                ocr_provider_used, vlm_warnings,
            ),
            pii_entities_pages=page_pii,
            pii_entities_narrative=narrative_pii,
            source_image_paths=source_image_paths,
            export_dir=Path(cfg.paths.export_dir),
            work_dir=doc_work,
            config=cfg,
        )
    else:
        export_result = ExportResult(
            skipped=True,
            skip_reason="; ".join(qa.blocking_reasons) or "qa.export_blocked",
        )

    return ReportArtifact(
        file_entry=entry,
        inspection=inspection,
        document_ir=document_ir,
        text_source=text_source,
        template_match=template_match,
        diagram=diagram,
        narrative=narrative,
        qa=qa,
        pii_entities_pages=page_pii,
        pii_entities_narrative=narrative_pii,
        ocr_provider_used=ocr_provider_used,
        vlm_warnings=list(vlm_warnings),
        export_result=export_result,
        export_blocked=qa.export_blocked,
        blocking_reasons=list(qa.blocking_reasons),
        work_dir=str(doc_work) if rendered or qa.export_blocked else None,
    )


def _artifact_view(
    entry, inspection, document_ir, text_source,
    template_match, diagram, narrative, qa,
    page_pii, narrative_pii, doc_work,
    ocr_provider_used, vlm_warnings,
) -> ReportArtifact:
    """Lightweight ReportArtifact used by the exporter (avoids circular wiring)."""
    return ReportArtifact(
        file_entry=entry,
        inspection=inspection,
        document_ir=document_ir,
        text_source=text_source,
        template_match=template_match,
        diagram=diagram,
        narrative=narrative,
        qa=qa,
        pii_entities_pages=list(page_pii),
        pii_entities_narrative=list(narrative_pii),
        ocr_provider_used=ocr_provider_used,
        vlm_warnings=list(vlm_warnings),
        work_dir=str(doc_work),
        export_blocked=qa.export_blocked,
        blocking_reasons=list(qa.blocking_reasons),
    )


def run_pipeline(
    input_dir: str | Path,
    *,
    config: AppConfig | None = None,
    backend: PDFImageBackend | None = None,
    template_registry: TemplateRegistry | None = None,
) -> PipelineRunResult:
    cfg = config or load_config()
    backend = backend or PypdfiumPDFImageBackend()
    work_root = _work_dir(cfg)

    paths = scan_directory(Path(input_dir))
    entries = build_file_manifest(paths)

    registry = (
        template_registry
        if template_registry is not None
        else _build_template_registry(cfg)
    )

    ocr_providers = _instantiate_ocr_chain(cfg)
    vlm_providers = _instantiate_vlm_chain(cfg)
    pii_providers = _instantiate_pii_chain(cfg)
    try:
        artifacts = [
            _process_one(
                entry,
                backend,
                ocr_providers,
                vlm_providers,
                pii_providers,
                work_root,
                registry,
                cfg,
            )
            for entry in entries
        ]
    finally:
        for provider in ocr_providers:
            provider.close()
        for provider in vlm_providers:
            provider.close()
        for provider in pii_providers:
            provider.close()

    return PipelineRunResult(
        config=cfg,
        file_entries=entries,
        artifacts=artifacts,
        template_registry=registry,
    )
