"""Phase 9 anchor-matching utility tests.

Pure-stdlib (difflib) implementation; tests must verify normalization
behaviour AND fuzzy thresholds without admitting unrelated matches.
"""
from __future__ import annotations

import pytest

from care.extraction.anchor_match import (
    DEFAULT_FUZZY_THRESHOLD,
    AnchorCoverage,
    find_anchor,
    normalize_anchor,
    score_anchor_coverage,
)


# ----- normalize_anchor ----------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Narrative", "narrative"),
        ("NARRATIVE", "narrative"),
        ("  Narrative  ", "narrative"),
        ("Narrative:", "narrative"),
        (":Narrative:", "narrative"),
        ("Narra\ttive", "narra tive"),
        ("Narra\n\ntive", "narra tive"),
        ("Officer's Name", "officer's name"),
        ("VIN:", "vin"),
        ("---Crash---", "crash"),
        ("", ""),
    ],
)
def test_normalize_strips_outer_punctuation_and_collapses_whitespace(
    raw: str, expected: str
) -> None:
    assert normalize_anchor(raw) == expected


def test_normalize_preserves_internal_punctuation() -> None:
    assert normalize_anchor("U.S.A.") == "u.s.a"


def test_normalize_handles_non_string() -> None:
    assert normalize_anchor(None) == ""  # type: ignore[arg-type]
    assert normalize_anchor(123) == ""  # type: ignore[arg-type]


# ----- find_anchor: exact path --------------------------------------------


def test_find_anchor_exact_substring() -> None:
    out = find_anchor("Narrative", "Officer found Narrative section")
    assert out.found and out.is_exact
    assert out.score == 1.0
    assert out.matched_text == "Narrative"
    assert out.matched_offset == 14


def test_find_anchor_exact_case_insensitive() -> None:
    out = find_anchor("Narrative", "officer found NARRATIVE section")
    assert out.found and out.is_exact
    assert out.matched_text == "NARRATIVE"


def test_find_anchor_exact_with_outer_punctuation_in_haystack() -> None:
    """Haystack token has trailing punctuation but the anchor does
    not. Normalization strips outer punctuation on the token, so this
    counts as an exact match — not fuzzy."""
    out = find_anchor("Narrative", "officer found NARRATIVE: paragraph")
    assert out.found and out.is_exact


def test_find_anchor_search_from_offset() -> None:
    """Two occurrences of the anchor; search_from skips the first."""
    text = "Narrative section contains Narrative again"
    first = find_anchor("Narrative", text)
    second = find_anchor("Narrative", text, search_from=first.matched_offset + 1)
    assert second.found
    assert second.matched_offset and second.matched_offset > first.matched_offset


# ----- find_anchor: fuzzy path --------------------------------------------


def test_find_anchor_fuzzy_one_char_typo() -> None:
    """OCR mistake: 'Narrative' read as 'Narrahve'. Fuzzy must catch it."""
    out = find_anchor("Narrative", "officer found Narrahve section")
    assert out.found and out.is_fuzzy
    assert out.score >= DEFAULT_FUZZY_THRESHOLD


def test_find_anchor_fuzzy_two_char_typo() -> None:
    out = find_anchor("Narrative", "officer found Narrabhve section")
    if out.found:
        # If matched, must be fuzzy and pass the threshold.
        assert out.is_fuzzy
        assert out.score >= DEFAULT_FUZZY_THRESHOLD


def test_find_anchor_fuzzy_rejects_unrelated() -> None:
    """A completely different word must NOT match, even at fuzzy."""
    out = find_anchor("Narrative", "Witness Statement Officer Driver")
    assert not out.found


def test_find_anchor_disabled_fuzzy() -> None:
    out = find_anchor(
        "Narrative", "officer found Narrahve section", allow_fuzzy=False
    )
    assert not out.found


def test_find_anchor_empty_anchor_or_haystack() -> None:
    assert not find_anchor("", "some text").found
    assert not find_anchor("   ", "some text").found
    assert not find_anchor("Narrative", "").found


# ----- score_anchor_coverage ----------------------------------------------


def test_score_coverage_all_exact() -> None:
    cov = score_anchor_coverage(["Narrative", "Crash"], "Narrative Crash Report")
    assert cov.found_exact == ("Narrative", "Crash")
    assert cov.found_fuzzy == ()
    assert cov.missing == ()
    assert cov.coverage_score == 1.0


def test_score_coverage_mixed_exact_and_fuzzy() -> None:
    cov = score_anchor_coverage(
        ["Narrative", "Crash"], "Narrahve Crash Report"  # OCR misread
    )
    assert "Crash" in cov.found_exact
    assert "Narrative" in cov.found_fuzzy
    # Fuzzy hits are discounted to 0.8 — coverage stays below 1.0.
    assert cov.coverage_score < 1.0
    assert cov.coverage_score >= 0.9


def test_score_coverage_with_missing_anchors() -> None:
    cov = score_anchor_coverage(
        ["Narrative", "Witness Statement"], "Narrative section only"
    )
    assert cov.found_exact == ("Narrative",)
    assert cov.missing == ("Witness Statement",)
    assert 0.0 < cov.coverage_score < 1.0


def test_score_coverage_empty_anchor_list() -> None:
    cov = score_anchor_coverage([], "any text here")
    assert cov.coverage_score == 0.0


# ----- regression: fuzzy must not promote non-anchors --------------------


def test_fuzzy_does_not_match_short_substring_overlap() -> None:
    """The matcher uses token-aligned windows, not raw substring
    sliding; this prevents 'Narr' inside a longer word from accidentally
    triggering a fuzzy match."""
    out = find_anchor("Narrative", "Narrowing")
    # SequenceMatcher ratio between 'narrative' and 'narrowing' is
    # roughly 0.6 — well below threshold. Must NOT match.
    assert not out.found
