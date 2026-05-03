"""Locked configuration keys (Phase 13.2).

This module is the single source of truth for keys that no caller —
GUI, CLI, scripts, or hand-edited YAML — may flip. Each entry encodes
a non-negotiable privacy or offline guarantee and the reason a future
operator might be tempted to flip it.

Two consumers import from here:

- ``care/api/routes_config.py`` — the validate / locked-keys
  endpoints powering the read-only banners and the PATCH gate.
- ``scripts/governance_check.py`` — the CI gate, so any change to this
  table immediately changes both the runtime guard and the static
  check (the two cannot drift).

Soft acknowledgements (e.g. ``offline.enabled: false`` for legal cloud
LLM use, ``server.expose_to_network: true`` for trusted intranets)
are NOT in this table. Those decisions belong to a separate
"requires-explicit-acknowledgement" layer that lands with the form
editor in Phase 13.5.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ImmutableRule:
    path: str
    forbidden_value: Any
    reason: str


IMMUTABLE_RULES: tuple[ImmutableRule, ...] = (
    ImmutableRule(
        path="export.include_original_pdf",
        forbidden_value=True,
        reason=(
            "Public exports must never include original PDFs."
        ),
    ),
    ImmutableRule(
        path="export.include_unredacted_text",
        forbidden_value=True,
        reason=(
            "Public exports must never include unredacted narratives."
        ),
    ),
    ImmutableRule(
        path="export.include_debug_artifacts",
        forbidden_value=True,
        reason=(
            "Public exports must never include raw OCR/VLM/PII debug "
            "artifacts."
        ),
    ),
    ImmutableRule(
        path="logging.log_raw_pii",
        forbidden_value=True,
        reason=(
            "Logs must never contain raw PII."
        ),
    ),
    ImmutableRule(
        path="logging.redact_pii",
        forbidden_value=False,
        reason=(
            "Log redaction must remain enabled."
        ),
    ),
)


def get_value_at_path(data: Any, dotted: str) -> Any:
    """Return the value at ``dotted`` (``a.b.c``) in a nested dict.

    Returns ``None`` when any intermediate key is missing — the
    caller treats a missing key as "no rule applies", which is
    correct: a config that omits ``logging.log_raw_pii`` falls back
    to the safe default declared in ``AppConfig``.
    """
    node: Any = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def check_immutable_violations(config: dict[str, Any]) -> list[str]:
    """Return a list of human-readable violation strings.

    Empty list = no rule violated. Each violation string includes the
    dotted path, the forbidden value, and the reason — suitable for
    display in the GUI without further formatting.
    """
    violations: list[str] = []
    for rule in IMMUTABLE_RULES:
        actual = get_value_at_path(config, rule.path)
        if actual == rule.forbidden_value:
            violations.append(
                f"{rule.path}={rule.forbidden_value!r} is locked: "
                f"{rule.reason}"
            )
    return violations


def list_locked_keys() -> list[dict[str, Any]]:
    """Return the immutable rules as a JSON-friendly list.

    Used by ``GET /api/config/locked-keys`` so the frontend can grey
    out fields the operator cannot touch.
    """
    return [
        {
            "path": rule.path,
            "forbidden_value": rule.forbidden_value,
            "reason": rule.reason,
        }
        for rule in IMMUTABLE_RULES
    ]


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Return a new dict where ``patch`` overrides ``base`` recursively.

    Lists / scalars are replaced wholesale (they're values, not
    containers — half-merging a list of provider names would produce
    a chain the operator never asked for).
    """
    out: dict[str, Any] = dict(base)
    for key, value in patch.items():
        if (
            key in out
            and isinstance(out[key], dict)
            and isinstance(value, dict)
        ):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out
