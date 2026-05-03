"""Text redactor — placeholder substitution."""
from __future__ import annotations

from care.pii.entities import PIIEntity
from care.redaction import redact_text


def _e(t, s, e):
    return PIIEntity(
        entity_type=t, text="X" * (e - s), start_offset=s, end_offset=e,
        provider="regex", detection_reason="r:t", sources=["regex"],
    )


def test_redact_text_replaces_with_placeholders() -> None:
    text = "phone 555-123-4567 email a@b.co"
    entities = [
        _e("PHONE_NUMBER", 6, 18),
        _e("EMAIL", 25, 31),
    ]
    redacted, applied = redact_text(text, entities)
    assert redacted == "phone [PHONE_NUMBER] email [EMAIL]"
    assert len(applied) == 2


def test_redact_text_preserves_left_to_right_in_applied_list() -> None:
    text = "X1 X2 X3"
    entities = [
        _e("VIN", 0, 2),
        _e("PHONE_NUMBER", 3, 5),
        _e("EMAIL", 6, 8),
    ]
    _, applied = redact_text(text, entities)
    types = [e.entity_type for e in applied]
    assert types == ["VIN", "PHONE_NUMBER", "EMAIL"]


def test_redact_text_skips_invalid_offsets() -> None:
    entities = [
        _e("PHONE_NUMBER", -1, 5),
        _e("EMAIL", 5, 1000),
        _e("VIN", 5, 5),
    ]
    out, applied = redact_text("hello world", entities)
    assert out == "hello world"
    assert applied == []


def test_redact_text_returns_unchanged_when_no_entities() -> None:
    out, applied = redact_text("nothing to redact", [])
    assert out == "nothing to redact"
    assert applied == []


def test_redact_text_handles_overlapping_after_merge() -> None:
    """Caller is expected to merge entities first; redactor still tolerates it."""
    text = "phone 555-123-4567"
    entities = [_e("PHONE_NUMBER", 6, 18), _e("PHONE_NUMBER", 6, 18)]
    out, _ = redact_text(text, entities)
    # Both substitutions land on the same span; result still placeholder-only.
    assert "555-123-4567" not in out
    assert "[PHONE_NUMBER]" in out
