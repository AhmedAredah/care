"""Replace PII spans with typed placeholders."""
from __future__ import annotations

from ..pii.entities import PIIEntity
from .policies import placeholder_for


def redact_text(
    text: str,
    entities: list[PIIEntity],
) -> tuple[str, list[PIIEntity]]:
    """Return (redacted_text, applied_entities).

    Entities are applied from the right edge of `text` leftward so that
    earlier offsets stay valid as later spans get replaced.
    """
    valid: list[PIIEntity] = []
    for entity in entities:
        if entity.start_offset is None or entity.end_offset is None:
            continue
        if entity.start_offset < 0 or entity.end_offset > len(text):
            continue
        if entity.start_offset >= entity.end_offset:
            continue
        valid.append(entity)

    valid.sort(key=lambda e: (e.start_offset or 0), reverse=True)

    redacted = text
    applied: list[PIIEntity] = []
    for entity in valid:
        placeholder = placeholder_for(entity.entity_type)
        redacted = (
            redacted[: entity.start_offset]
            + placeholder
            + redacted[entity.end_offset :]
        )
        applied.append(entity)

    applied.reverse()  # left-to-right reading order
    return redacted, applied
