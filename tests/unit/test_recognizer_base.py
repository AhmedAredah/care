"""``RegexRecognizer`` base-class contract.

Each recognizer is a subclass that declares ``entity_type``,
``detection_reason``, ``default_confidence``, ``pattern``, and
optionally a ``capture_group`` index or an ``is_valid`` filter. This
test pins the inherited ``find()`` behaviour so a future change to
the base can't silently shift recognizer outputs.
"""
from __future__ import annotations

import re

from care.pii.recognizers import (
    ALL_RECOGNIZERS,
    Match,
    RegexRecognizer,
    VinRecognizer,
)


class _GroupZeroFixture(RegexRecognizer):
    entity_type = "FIXTURE"
    detection_reason = "fixture_group_zero"
    default_confidence = 0.55
    pattern = re.compile(r"\b\d{3}\b")


class _GroupOneFixture(RegexRecognizer):
    entity_type = "FIXTURE_LABELLED"
    detection_reason = "fixture_group_one"
    default_confidence = 0.77
    capture_group = 1
    pattern = re.compile(r"ID:\s*([A-Z]{3})")


class _ValidatedFixture(RegexRecognizer):
    entity_type = "FIXTURE_VALIDATED"
    detection_reason = "fixture_validated"
    default_confidence = 0.6
    pattern = re.compile(r"\b\d{4}\b")

    @classmethod
    def is_valid(cls, value: str) -> bool:
        # Reject the unlucky number.
        return value != "1313"


def test_full_match_emits_match_with_group_zero_offsets() -> None:
    matches = _GroupZeroFixture.find("alpha 123 beta 456")
    assert [m.text for m in matches] == ["123", "456"]
    # Confirm offsets point at the matched span, not the whole text.
    assert "alpha 123 beta 456"[matches[0].start : matches[0].end] == "123"
    assert "alpha 123 beta 456"[matches[1].start : matches[1].end] == "456"


def test_default_confidence_is_propagated() -> None:
    matches = _GroupZeroFixture.find("999")
    assert matches[0].confidence == _GroupZeroFixture.default_confidence


def test_label_anchored_returns_capture_group_one() -> None:
    matches = _GroupOneFixture.find("note ID: ABC and ID: XYZ done")
    assert [m.text for m in matches] == ["ABC", "XYZ"]
    # Offsets point at the captured value, not the "ID:" prefix.
    text = "note ID: ABC and ID: XYZ done"
    assert text[matches[0].start : matches[0].end] == "ABC"


def test_is_valid_filter_drops_rejected_matches() -> None:
    matches = _ValidatedFixture.find("seen 1212 1313 1414")
    assert [m.text for m in matches] == ["1212", "1414"]


def test_is_valid_default_accepts_everything() -> None:
    """Subclasses that don't override ``is_valid`` keep every regex hit."""
    matches = _GroupZeroFixture.find("100 200 300")
    assert len(matches) == 3


def test_each_registered_recognizer_declares_required_attributes() -> None:
    """Loud guarantee — adding a new recognizer that forgets to set
    ``entity_type``, ``detection_reason``, or ``pattern`` will fail
    here long before it confuses the redaction pipeline."""
    for cls in ALL_RECOGNIZERS:
        assert issubclass(cls, RegexRecognizer), cls
        assert cls.entity_type, f"{cls.__name__}.entity_type unset"
        assert cls.detection_reason, f"{cls.__name__}.detection_reason unset"
        assert isinstance(cls.pattern, re.Pattern), f"{cls.__name__}.pattern not compiled"
        assert 0.0 < cls.default_confidence <= 1.0, cls


def test_module_level_find_alias_still_works() -> None:
    """Each recognizer module still exposes a top-level ``find``
    callable that delegates to the class. Existing call-sites
    (`vin.find(text)`) keep working without instantiating anything."""
    from care.pii.recognizers import phone, vin

    assert phone.find("call 555-123-4567 today")[0].text == "555-123-4567"
    assert vin.find("VIN 1HGCM82633A004352 ok")[0].text == "1HGCM82633A004352"


def test_vin_validator_overrides_is_valid() -> None:
    """VIN's check-digit validator must be wired into the inherited
    ``find()`` — the regex matches a string, ``is_valid`` filters it
    out, ``find`` skips it. This is the integration that proves the
    base's filter hook is the right shape."""
    # Same NHTSA example mutated at position 9 to fail the check digit.
    assert VinRecognizer.find("VIN 1M8GDM9AZKP042788 here") == []
    # The unmodified example passes.
    matches = VinRecognizer.find("VIN 1M8GDM9AXKP042788 here")
    assert len(matches) == 1
    assert matches[0].text == "1M8GDM9AXKP042788"


def test_match_dataclass_is_frozen() -> None:
    """``Match`` is the recognizer's only public-facing dataclass; if
    a future change drops the ``frozen=True`` someone will start
    mutating it from a caller and break detection_reason aggregation."""
    m = Match("v", 0, 1, 0.5)
    try:
        m.text = "different"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("Match should be frozen")
