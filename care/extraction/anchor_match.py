"""Anchor normalization + fuzzy matching (Phase 9).

Pure stdlib (``difflib``) — no new external dependencies. The matcher is
deliberately conservative: exact match always wins, fuzzy match only
fires when an exact pass found nothing, and every fuzzy hit carries a
score so callers can decide whether to treat it as authoritative or
emit a "review" flag.

Two reasons OCR-driven anchor matching needs fuzziness here:

1. **Whitespace and casing drift.** ``"Narrative"`` vs ``"NARRATIVE "``
   vs ``"narrative:"`` vs ``"Narra tive"`` — pre-OCR forms differ from
   the operator's authoring choice in trivial but exact-match-fatal
   ways. Normalization handles those.

2. **Single-character OCR errors.** ``"Narrative"`` mis-recognized as
   ``"Narrahve"`` or ``"Narratlve"``. Normalization can't fix those;
   bounded-edit-distance fuzzy match can.

Fuzzy match returns a score in ``[0.0, 1.0]`` (``difflib`` ratio) and a
boolean indicating whether the match was exact. Callers choose their
own confidence threshold (``DEFAULT_FUZZY_THRESHOLD`` is the
project-wide default — 0.85 — picked to catch one or two edits in a
typical anchor word without admitting completely different words).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Optional

DEFAULT_FUZZY_THRESHOLD = 0.78
"""Minimum SequenceMatcher ratio for a fuzzy match to be accepted.

Empirically: 0.78 admits one OCR error on a 6+ char word
(``"Narrative"`` → ``"Narrahve"`` ≈ 0.82 via deletion;
``"Narrative"`` → ``"Narratlve"`` ≈ 0.89 via substitution) while
rejecting unrelated words (``"Narrative"`` vs ``"Officer"`` ≈ 0.13;
vs ``"Narrowing"`` ≈ 0.56). Lowering further is risky — it admits
near-misses like ``"Narrowing"``.

Callers needing stricter matching can pass an explicit
``fuzzy_threshold`` kwarg.
"""

_PUNCT_STRIP_RE = re.compile(r"^[\s\W_]+|[\s\W_]+$", flags=re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_anchor(value: str) -> str:
    """Lowercase, NFC-normalize, collapse whitespace, strip outer punctuation.

    Internal punctuation is preserved so anchors like ``"VIN:"`` keep
    their colon (in case the document text has it too) — the strip
    only attacks leading/trailing punctuation that operators commonly
    paste alongside the actual anchor text.
    """
    if not isinstance(value, str):
        return ""
    nfc = unicodedata.normalize("NFC", value)
    folded = nfc.casefold()
    collapsed = _WHITESPACE_RE.sub(" ", folded).strip()
    stripped = _PUNCT_STRIP_RE.sub("", collapsed)
    return stripped


@dataclass(frozen=True)
class AnchorMatch:
    """A single anchor-vs-text match decision.

    ``method`` is ``"exact"`` when the normalized anchor was found as a
    substring of the normalized haystack, ``"fuzzy"`` when it was only
    found via :func:`difflib.SequenceMatcher`, or ``"miss"`` when no
    candidate cleared the threshold. ``score`` is in ``[0.0, 1.0]`` —
    1.0 for exact matches, the SequenceMatcher ratio for fuzzy.
    ``matched_text`` echoes the haystack's actual text (verbatim slice,
    not the normalized form) so a caller can distinguish ``"NARRATIVE"``
    from ``"Narrative"`` in logs.
    """

    found: bool
    method: str  # "exact" | "fuzzy" | "miss"
    score: float
    matched_text: Optional[str]
    matched_offset: Optional[int]

    @property
    def is_exact(self) -> bool:
        return self.method == "exact"

    @property
    def is_fuzzy(self) -> bool:
        return self.method == "fuzzy"


def find_anchor(
    anchor: str,
    haystack: str,
    *,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    allow_fuzzy: bool = True,
    search_from: int = 0,
) -> AnchorMatch:
    """Find ``anchor`` in ``haystack`` (exact, then fuzzy).

    ``search_from`` is a haystack offset; this lets callers chain
    "find anchor_start, then find anchor_end after it" without picking
    up an end anchor that physically precedes the start.

    Empty/blank anchors return ``found=False, method="miss"`` so the
    caller's behavior is the same as if no anchor were declared.
    """
    if not anchor or not anchor.strip():
        return AnchorMatch(False, "miss", 0.0, None, None)
    if not haystack:
        return AnchorMatch(False, "miss", 0.0, None, None)

    norm_anchor = normalize_anchor(anchor)
    if not norm_anchor:
        return AnchorMatch(False, "miss", 0.0, None, None)

    # ---- exact normalized substring (cheapest) ----
    norm_haystack = normalize_anchor(haystack[search_from:])
    if norm_anchor in norm_haystack:
        # Map back to the original haystack: the cheapest correct way
        # is a case-insensitive find on the raw text.
        idx = haystack.lower().find(anchor.lower(), search_from)
        if idx >= 0:
            return AnchorMatch(
                True, "exact", 1.0, haystack[idx : idx + len(anchor)], idx
            )
        # Punctuation-only differences: scan tokens.
        token_match = _scan_normalized_tokens(haystack, anchor, search_from)
        if token_match is not None:
            tok_text, tok_offset = token_match
            return AnchorMatch(True, "exact", 1.0, tok_text, tok_offset)

    if not allow_fuzzy:
        return AnchorMatch(False, "miss", 0.0, None, None)

    # ---- fuzzy via SequenceMatcher over candidate windows ----
    best: AnchorMatch = AnchorMatch(False, "miss", 0.0, None, None)
    anchor_word_count = max(1, len(norm_anchor.split()))
    haystack_tail = haystack[search_from:]
    tokens = list(_token_spans(haystack_tail))
    for window_size in {anchor_word_count, anchor_word_count + 1, max(1, anchor_word_count - 1)}:
        if window_size <= 0 or window_size > len(tokens):
            continue
        for start_i in range(0, len(tokens) - window_size + 1):
            span_start = tokens[start_i][0]
            span_end = tokens[start_i + window_size - 1][1]
            candidate_raw = haystack_tail[span_start:span_end]
            candidate_norm = normalize_anchor(candidate_raw)
            if not candidate_norm:
                continue
            ratio = SequenceMatcher(None, norm_anchor, candidate_norm).ratio()
            if ratio > best.score and ratio >= fuzzy_threshold:
                best = AnchorMatch(
                    True,
                    "fuzzy",
                    round(ratio, 4),
                    candidate_raw,
                    search_from + span_start,
                )
    return best


def _token_spans(text: str) -> list[tuple[int, int]]:
    """Return [(start, end), …] offsets of whitespace-separated tokens."""
    spans: list[tuple[int, int]] = []
    in_tok = False
    start = 0
    for i, ch in enumerate(text):
        if ch.isspace():
            if in_tok:
                spans.append((start, i))
                in_tok = False
        else:
            if not in_tok:
                start = i
                in_tok = True
    if in_tok:
        spans.append((start, len(text)))
    return spans


def _scan_normalized_tokens(
    haystack: str, anchor: str, search_from: int
) -> Optional[tuple[str, int]]:
    """Walk the haystack token by token, normalize each, and return the
    first token whose normalized form equals the normalized anchor.
    Used to catch punctuation-only and casing-only differences that
    a raw ``str.find`` misses (e.g., haystack contains ``"NARRATIVE:"``
    while the anchor was authored as ``"Narrative"``)."""
    norm_anchor = normalize_anchor(anchor)
    if not norm_anchor:
        return None
    tail = haystack[search_from:]
    for token_start, token_end in _token_spans(tail):
        token_text = tail[token_start:token_end]
        if normalize_anchor(token_text) == norm_anchor:
            return token_text, search_from + token_start
    return None


# ----- coverage helper used by the template scorer -----------------------


@dataclass(frozen=True)
class AnchorCoverage:
    """Aggregate report over a list of anchor strings."""

    found_exact: tuple[str, ...]
    found_fuzzy: tuple[str, ...]
    missing: tuple[str, ...]
    matches: tuple[AnchorMatch, ...]

    @property
    def coverage_score(self) -> float:
        """Coverage in ``[0..1]``, with fuzzy matches discounted to 0.8.

        Discounting fuzzy hits keeps two near-identical templates
        (``v1`` differing from ``v2`` only on one anchor's spelling)
        distinguishable: the template whose anchors match exactly will
        outscore the one that needed fuzzy coverage.
        """
        total = len(self.found_exact) + len(self.found_fuzzy) + len(self.missing)
        if total == 0:
            return 0.0
        return (len(self.found_exact) + 0.8 * len(self.found_fuzzy)) / total


def score_anchor_coverage(
    anchors: list[str],
    haystack: str,
    *,
    fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    allow_fuzzy: bool = True,
) -> AnchorCoverage:
    """Compute exact/fuzzy/missing coverage for a list of anchors."""
    found_exact: list[str] = []
    found_fuzzy: list[str] = []
    missing: list[str] = []
    matches: list[AnchorMatch] = []
    for anchor in anchors:
        match = find_anchor(
            anchor,
            haystack,
            fuzzy_threshold=fuzzy_threshold,
            allow_fuzzy=allow_fuzzy,
        )
        matches.append(match)
        if match.is_exact:
            found_exact.append(anchor)
        elif match.is_fuzzy:
            found_fuzzy.append(anchor)
        else:
            missing.append(anchor)
    return AnchorCoverage(
        found_exact=tuple(found_exact),
        found_fuzzy=tuple(found_fuzzy),
        missing=tuple(missing),
        matches=tuple(matches),
    )
