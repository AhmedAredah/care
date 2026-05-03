"""Audit-event helpers.

Audit events MUST NEVER carry raw PII. Only the entity type, offsets,
confidence, provider, and review/mapping flags are recorded.
"""
from __future__ import annotations

from typing import Any

from ..pii.entities import PIIEntity


def audit_event_dict(entity: PIIEntity) -> dict[str, Any]:
    return {
        "entity_type": entity.entity_type,
        "page_index": entity.page_index,
        "start_offset": entity.start_offset,
        "end_offset": entity.end_offset,
        "confidence": entity.confidence,
        "provider": entity.provider,
        "providers": list(entity.sources or []),
        "detection_reason": entity.detection_reason,
        "can_map_to_image_coordinates": entity.can_map_to_image_coordinates,
        "requires_review": entity.requires_review,
    }
