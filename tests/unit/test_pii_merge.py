"""PII entity merging."""
from __future__ import annotations

from care.pii.entities import PIIEntity
from care.pii.merge import merge_entities


def _entity(*, t="PHONE_NUMBER", start=0, end=10, page=0, prov="regex", reason="r:page",
            text="555-123-4567") -> PIIEntity:
    return PIIEntity(
        entity_type=t,
        text=text,
        start_offset=start,
        end_offset=end,
        page_index=page,
        confidence=0.85,
        provider=prov,
        detection_reason=reason,
        sources=[prov],
    )


def test_overlapping_same_type_entities_are_merged() -> None:
    a = _entity(start=10, end=20)
    b = _entity(start=15, end=25)
    out = merge_entities([a, b])
    assert len(out) == 1
    assert out[0].start_offset == 10
    assert out[0].end_offset == 25
    assert out[0].entity_type == "PHONE_NUMBER"


def test_disjoint_same_type_entities_are_kept_separate() -> None:
    a = _entity(start=0, end=10)
    b = _entity(start=20, end=30)
    out = merge_entities([a, b])
    assert len(out) == 2


def test_cross_type_overlap_is_kept() -> None:
    a = _entity(t="PERSON_NAME", start=0, end=15, text="Officer Smith")
    b = _entity(t="SIGNATURE", start=0, end=20, text="Officer Smith etc")
    out = merge_entities([a, b])
    types = sorted(e.entity_type for e in out)
    assert types == ["PERSON_NAME", "SIGNATURE"]


def test_provider_sources_are_combined() -> None:
    a = _entity(start=0, end=10, prov="regex")
    b = _entity(start=5, end=15, prov="presidio")
    a.sources = ["regex"]
    b.sources = ["presidio"]
    out = merge_entities([a, b])
    assert len(out) == 1
    assert sorted(out[0].sources) == ["presidio", "regex"]


def test_different_pages_are_not_merged() -> None:
    a = _entity(page=0, start=0, end=10)
    b = _entity(page=1, start=0, end=10)
    out = merge_entities([a, b])
    assert len(out) == 2


def test_different_scopes_are_not_merged() -> None:
    """Page-scope and narrative-scope entities never collapse, even at the same offsets."""
    a = _entity(reason="r:page", start=0, end=10)
    b = _entity(reason="r:narrative", start=0, end=10)
    out = merge_entities([a, b])
    assert len(out) == 2


def test_inputs_are_not_mutated() -> None:
    a = _entity(start=0, end=10)
    b = _entity(start=5, end=15)
    a_before = (a.start_offset, a.end_offset, list(a.sources))
    b_before = (b.start_offset, b.end_offset, list(b.sources))
    merge_entities([a, b])
    assert (a.start_offset, a.end_offset, list(a.sources)) == a_before
    assert (b.start_offset, b.end_offset, list(b.sources)) == b_before
