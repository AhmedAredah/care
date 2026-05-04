"""Entity merging / deduplication.

Same-type entities whose offset ranges overlap (on the same page and
detection scope) are merged into a single entity that spans the union;
all provider names are preserved in `sources`.

Cross-type overlaps are *kept* — for example, a PERSON_NAME inside a
SIGNATURE label should be redacted with the more specific placeholder,
and the conservative thing is to surface both detections so downstream
auditing has full provenance.
"""
from __future__ import annotations

import copy
from collections import defaultdict
from collections.abc import Iterable

from .entities import PIIEntity


def _key(entity: PIIEntity) -> tuple:
    """Identity for grouping: page + entity type + scope marker (page vs narrative)."""
    scope = ""
    reason = entity.detection_reason or ""
    if ":" in reason:
        scope = reason.rsplit(":", 1)[-1]
    return (entity.page_index, entity.entity_type, scope)


def _spans_overlap(a: PIIEntity, b: PIIEntity) -> bool:
    if a.start_offset is None or a.end_offset is None:
        return False
    if b.start_offset is None or b.end_offset is None:
        return False
    return not (a.end_offset <= b.start_offset or b.end_offset <= a.start_offset)


def merge_entities(entities: Iterable[PIIEntity]) -> list[PIIEntity]:
    """Merge same-(page, type, scope) overlapping entities into wider unions.

    Inputs are deep-copied; original entities are never mutated.
    """
    buckets: dict[tuple, list[PIIEntity]] = defaultdict(list)
    for entity in entities:
        buckets[_key(entity)].append(copy.copy(entity))

    merged: list[PIIEntity] = []
    for bucket in buckets.values():
        bucket.sort(key=lambda e: ((e.start_offset or 0), -(e.end_offset or 0)))
        for entity in bucket:
            if entity.sources:
                entity.sources = list(entity.sources)
            else:
                entity.sources = [entity.provider] if entity.provider else []

            absorbed = False
            for existing in merged:
                if _key(existing) != _key(entity):
                    continue
                if _spans_overlap(existing, entity):
                    new_start = min(existing.start_offset or 0, entity.start_offset or 0)
                    new_end = max(existing.end_offset or 0, entity.end_offset or 0)
                    existing.start_offset = new_start
                    existing.end_offset = new_end
                    existing.confidence = max(existing.confidence, entity.confidence)
                    existing.sources = list(
                        dict.fromkeys((existing.sources or []) + (entity.sources or []))
                    )
                    absorbed = True
                    break
            if not absorbed:
                merged.append(entity)

    merged.sort(key=lambda e: (e.page_index or 0, e.start_offset or 0))
    return merged
