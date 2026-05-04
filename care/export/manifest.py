"""Export manifest builder."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ..core.config import AppConfig
from ..pii.policies import REDACTION_POLICY_NAME

if TYPE_CHECKING:
    from ..workers.pipeline import ReportArtifact


def build_manifest(artifact: ReportArtifact, config: AppConfig) -> dict[str, Any]:
    template = artifact.template_match
    return {
        "source_sha256": artifact.file_entry.sha256,
        "source_file_name": artifact.file_entry.name,
        "template_id": template.template_id,
        "template_version": template.version,
        "template_confidence": template.confidence,
        "ocr_provider": (config.ocr.provider_chain or [None])[0],
        "ocr_provider_version": "0.1.0",
        "document_ai_providers": [],
        "pii_provider_chain": list(config.pii.provider_chain),
        "redaction_policy": REDACTION_POLICY_NAME,
        "export_contains_original_pdf": False,
        "export_contains_unredacted_text": False,
        "export_contains_raw_ocr_or_vlm_output": False,
        "requires_human_review": artifact.qa.requires_human_review,
        "diagram_confidence": artifact.qa.diagram_confidence,
        "narrative_confidence": artifact.qa.narrative_confidence,
        "text_source": artifact.text_source,
        "created_at": datetime.now(UTC).isoformat(),
    }
