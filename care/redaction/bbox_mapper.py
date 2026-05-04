"""Map text offsets in the joined-by-space page text back to word bboxes."""
from __future__ import annotations

from ..document_ir.models import Page, Word
from ..pii.entities import PIIEntity


def page_word_offsets(page: Page) -> list[tuple[int, int, Word]]:
    """Per-word `(start_char, end_char, Word)` against `' '.join(page.words.text)`."""
    offsets: list[tuple[int, int, Word]] = []
    cursor = 0
    for word in page.words:
        start = cursor
        end = start + len(word.text)
        offsets.append((start, end, word))
        cursor = end + 1  # the joining space
    return offsets


def map_text_offset_to_words(
    page: Page,
    start_char: int,
    end_char: int,
) -> list[Word]:
    """Words whose offset range overlaps `[start_char, end_char)`."""
    overlapping: list[Word] = []
    for word_start, word_end, word in page_word_offsets(page):
        if word_start >= end_char:
            break
        if word_end <= start_char:
            continue
        overlapping.append(word)
    return overlapping


def derive_bbox_from_words(words: list[Word]) -> list[float] | None:
    """Min/max union of every word bbox; None if no word carries a bbox."""
    bboxes = [w.bbox for w in words if w.bbox]
    if not bboxes:
        return None
    x0 = min(b[0] for b in bboxes)
    y0 = min(b[1] for b in bboxes)
    x1 = max(b[2] for b in bboxes)
    y1 = max(b[3] for b in bboxes)
    return [float(x0), float(y0), float(x1), float(y1)]


def attach_bbox_to_pii_entities(
    page: Page,
    entities: list[PIIEntity],
) -> list[PIIEntity]:
    """Attach an image-coord bbox to each entity when possible.

    Mutates entities in place. When a bbox cannot be derived (e.g. native
    PDF text without per-word coordinates) the entity is marked
    `requires_review=True` and `can_map_to_image_coordinates=False`.
    """
    for entity in entities:
        if entity.start_offset is None or entity.end_offset is None:
            entity.can_map_to_image_coordinates = False
            entity.requires_review = True
            continue
        words = map_text_offset_to_words(page, entity.start_offset, entity.end_offset)
        bbox = derive_bbox_from_words(words)
        if bbox is None:
            entity.bbox = None
            entity.can_map_to_image_coordinates = False
            entity.requires_review = True
        else:
            entity.bbox = bbox
            entity.can_map_to_image_coordinates = True
    return entities
