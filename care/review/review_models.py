"""Review-related dataclasses (Phase 3 surface)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewDecision:
    decision: str  # "ALLOW" | "BLOCK"
    reason: str = ""

    @classmethod
    def allow(cls) -> ReviewDecision:
        return cls(decision="ALLOW")

    @classmethod
    def block(cls, reason: str) -> ReviewDecision:
        return cls(decision="BLOCK", reason=reason)
