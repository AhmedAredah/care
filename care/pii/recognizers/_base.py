"""Shared types for crash-report-specific PII recognizers."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Match:
    text: str
    start: int
    end: int
    confidence: float = 0.85
