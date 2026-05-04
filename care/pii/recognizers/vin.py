"""VIN recognizer (ISO 3779 — 17 chars, no I/O/Q, mod-11 check digit).

Position 9 of a valid VIN is the mod-11 check digit computed from the
other 16 characters using the canonical letter-to-value transliteration
in 49 CFR §565 / ISO 3779. Strings that fit the alphabet but fail the
check digit are *not* VINs — they're false positives (random
alphanumeric IDs, form numbers, transaction codes). Skipping them
keeps the manifest's PII flags trustworthy and avoids redacting fields
that aren't actually VINs.
"""
from __future__ import annotations

import re

from ._base import Match

ENTITY_TYPE = "VIN"
DETECTION_REASON = "regex_vin_iso3779"
DEFAULT_CONFIDENCE = 0.92

PATTERN = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b")


# Letter → numeric value per 49 CFR §565.15. I, O, Q are excluded
# from the VIN alphabet entirely (already enforced by PATTERN).
_TRANSLITERATE: dict[str, int] = {
    **{c: int(c) for c in "0123456789"},
    "A": 1, "B": 2, "C": 3, "D": 4, "E": 5, "F": 6, "G": 7, "H": 8,
    "J": 1, "K": 2, "L": 3, "M": 4, "N": 5,
    "P": 7,
    "R": 9,
    "S": 2, "T": 3, "U": 4, "V": 5, "W": 6, "X": 7, "Y": 8, "Z": 9,
}

# Position weights, 1-indexed in the spec; 0-indexed here.
_WEIGHTS: tuple[int, ...] = (8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2)


def _passes_check_digit(vin: str) -> bool:
    """Apply the mod-11 check digit. Pre-condition: ``vin`` already
    matches PATTERN (17 chars, alphabet [A-HJ-NPR-Z0-9])."""
    total = sum(_WEIGHTS[i] * _TRANSLITERATE[vin[i]] for i in range(17))
    expected = "X" if total % 11 == 10 else str(total % 11)
    return vin[8] == expected


def find(text: str) -> list[Match]:
    out: list[Match] = []
    for m in PATTERN.finditer(text):
        candidate = m.group(0)
        if not _passes_check_digit(candidate):
            continue
        out.append(Match(candidate, m.start(), m.end(), DEFAULT_CONFIDENCE))
    return out
