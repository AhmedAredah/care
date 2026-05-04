"""Public exporter.

The exporter writes exactly five files for an allowed report:

    exports/report_<short_sha256>/
        diagram.redacted.png
        narrative.redacted.txt
        narrative.redacted.json
        manifest.json
        qa.json

It MUST refuse to write anything when `qa.export_blocked` is True. It
MUST NEVER write the original PDF/image, raw OCR/VLM dumps, or
unredacted text.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from ..core.config import AppConfig
from ..pii.entities import PIIEntity
from ..redaction import audit_event_dict, redact_image, redact_text
from .manifest import build_manifest
from .writers import write_json, write_text

if TYPE_CHECKING:
    from ..workers.pipeline import ReportArtifact

_log = logging.getLogger(__name__)


@dataclass
class ExportResult:
    written: list[str] = field(default_factory=list)
    skipped: bool = False
    skip_reason: str | None = None
    output_dir: str | None = None


def _qa_to_dict(qa) -> dict:
    return {
        "export_decision": qa.export_decision,
        "export_blocked": qa.export_blocked,
        "blocking_reasons": list(qa.blocking_reasons),
        "qa_flags": list(qa.qa_flags),
        "requires_human_review": qa.requires_human_review,
        "template_confidence": qa.template_confidence,
        "diagram_confidence": qa.diagram_confidence,
        "narrative_confidence": qa.narrative_confidence,
    }


def export_artifact(
    artifact: ReportArtifact,
    *,
    pii_entities_pages: list[PIIEntity],
    pii_entities_narrative: list[PIIEntity],
    source_image_paths: dict[int, Path],
    export_dir: Path | str,
    work_dir: Path | str,
    config: AppConfig,
) -> ExportResult:
    """Write the five public artifacts (or refuse and return an empty result).

    Refusal cases:
    - QA gate blocked the report: nothing is written, no directory is created.
    - Required intermediate (diagram crop, narrative text, page image) is
      missing: skip that artifact and emit a manifest/qa.json only.
    """
    if artifact.qa.export_blocked:
        _log.info(
            "exporter: skipping report %s (%s)",
            artifact.file_entry.sha256[:16],
            artifact.qa.export_decision,
        )
        return ExportResult(
            skipped=True,
            skip_reason="; ".join(artifact.qa.blocking_reasons) or "qa.export_blocked",
        )

    short_sha = artifact.file_entry.sha256[:16]
    out_dir = Path(export_dir) / f"report_{short_sha}"
    out_dir.mkdir(parents=True, exist_ok=True)
    work_path = Path(work_dir)

    written: list[str] = []

    # 1. diagram.redacted.png — redact the page image, then crop the diagram.
    diagram = artifact.diagram
    if (
        diagram is not None
        and diagram.bbox_pixels is not None
        and diagram.image_path is not None
    ):
        page_image_path = source_image_paths.get(diagram.page_index)
        if page_image_path is not None and Path(page_image_path).exists():
            page_entities = [
                e
                for e in pii_entities_pages
                if e.page_index == diagram.page_index and e.bbox is not None
            ]
            redacted_page_path = work_path / f"page_{diagram.page_index}.redacted.png"
            redact_image(
                page_image_path,
                page_entities,
                redacted_page_path,
            )
            with Image.open(redacted_page_path) as img:
                crop = img.crop(diagram.bbox_pixels)
                target = out_dir / "diagram.redacted.png"
                crop.save(target, format="PNG")
            written.append("diagram.redacted.png")

    # 2. narrative.redacted.txt + narrative.redacted.json
    narrative = artifact.narrative
    applied_entities: list[PIIEntity] = []
    redacted_narrative_text = ""
    if narrative is not None and narrative.text:
        redacted_narrative_text, applied_entities = redact_text(
            narrative.text, pii_entities_narrative
        )
        write_text(out_dir / "narrative.redacted.txt", redacted_narrative_text)
        written.append("narrative.redacted.txt")
        narrative_payload = {
            "text": redacted_narrative_text,
            "page_index": narrative.page_index,
            "text_source": narrative.text_source,
            "anchor_start": narrative.anchor_start,
            "anchor_end": narrative.anchor_end,
            "anchor_start_found": narrative.anchor_start_found,
            "anchor_end_found": narrative.anchor_end_found,
            "confidence": narrative.confidence,
            "entities_redacted": [audit_event_dict(e) for e in applied_entities],
        }
        write_json(out_dir / "narrative.redacted.json", narrative_payload)
        written.append("narrative.redacted.json")

    # 3. manifest.json
    write_json(out_dir / "manifest.json", build_manifest(artifact, config))
    written.append("manifest.json")

    # 4. qa.json
    write_json(out_dir / "qa.json", _qa_to_dict(artifact.qa))
    written.append("qa.json")

    return ExportResult(
        written=written,
        skipped=False,
        output_dir=str(out_dir),
    )
