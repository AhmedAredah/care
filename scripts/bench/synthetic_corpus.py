"""Synthetic crash-narrative + label generator (Phase 1).

Produces a small, deterministic corpus of made-up crash narratives
with character-offset PII labels. Used by ``run_pii_bench.py`` to
score in-tree PII providers without needing access to a real
police-report corpus.

This is the Tier-A baseline. It is NOT a substitute for evaluation
on real reports — synthetic phrasing exercises the recognizers but
not the OCR-noise / abbreviation / wraparound failure modes that a
real corpus surfaces. v0.3.0 should add a held-out labelled set
sourced from a partner DOT.

Usage:
    python -m scripts.bench.synthetic_corpus --out scripts/bench/data/pii_corpus.jsonl

Each output line is a JSON object:
    {"text": "<narrative>", "labels": [{"entity_type": "...", "start": 12, "end": 25, "text": "..."}, ...]}
"""
from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass
class Span:
    entity_type: str
    text: str

    def to_label(self, start: int) -> dict:
        return {
            "entity_type": self.entity_type,
            "start": start,
            "end": start + len(self.text),
            "text": self.text,
        }


# Made-up but format-realistic data. None of these correspond to real
# people, vehicles, or addresses — that's the point of synthetic data.
_VINS = [
    "1HGCM82633A004352",
    "JH4KA8260MC012345",
    "5YJ3E1EA7KF317821",
    "WAUZZZ8E76A123456",
    "1FAFP404X1F123456",
]
_PLATES = ["TX-7AB-3421", "CA-9XYZ123", "NY-MNO-9876", "FL-CRA-4422", "WA-PLT-1199"]
_PHONES = ["(512) 555-0142", "713-555-0199", "+1 832 555 0177", "806.555.0123"]
_EMAILS = ["jane.doe@example.com", "officer.smith@dps.test", "witness@anon.example"]
_ADDRESSES = [
    "1234 Westheimer Rd, Houston, TX 77006",
    "5500 Lamar Blvd, Austin, TX 78751",
    "9911 Camp Bowie W, Fort Worth, TX 76116",
    "210 Main St, Dallas, TX 75202",
]
_PERSON_NAMES = [
    "John Q. Doe",
    "Maria L. Hernandez",
    "Michael Johnson",
    "Sarah Connor",
    "Robert E. Lee",
]


_TEMPLATES: list[tuple[str, list[str]]] = [
    (
        "Driver {NAME} (license plate {PLATE}, VIN {VIN}) was contacted at "
        "{ADDRESS}. Phone on file: {PHONE}.",
        ["NAME", "PLATE", "VIN", "ADDRESS", "PHONE"],
    ),
    (
        "Witness {NAME} reported the collision via email at {EMAIL}; "
        "vehicle plate {PLATE} fled westbound.",
        ["NAME", "EMAIL", "PLATE"],
    ),
    (
        "Officer logged VIN {VIN} for the at-fault vehicle. Owner of record "
        "lives at {ADDRESS} and was reachable at {PHONE}.",
        ["VIN", "ADDRESS", "PHONE"],
    ),
    (
        "Passenger {NAME} declined transport; emergency contact {PHONE} "
        "notified at scene.",
        ["NAME", "PHONE"],
    ),
    (
        "Citation issued to {NAME}, plate {PLATE}. Follow-up correspondence "
        "directed to {EMAIL}.",
        ["NAME", "PLATE", "EMAIL"],
    ),
]


def _slot_value(slot: str, rng: random.Random) -> Span:
    if slot == "NAME":
        return Span("PERSON_NAME", rng.choice(_PERSON_NAMES))
    if slot == "PLATE":
        return Span("LICENSE_PLATE", rng.choice(_PLATES))
    if slot == "VIN":
        return Span("VIN", rng.choice(_VINS))
    if slot == "ADDRESS":
        return Span("ADDRESS", rng.choice(_ADDRESSES))
    if slot == "PHONE":
        return Span("PHONE_NUMBER", rng.choice(_PHONES))
    if slot == "EMAIL":
        return Span("EMAIL", rng.choice(_EMAILS))
    raise ValueError(f"unknown slot: {slot}")


def generate(n: int, seed: int = 1337) -> Iterable[dict]:
    rng = random.Random(seed)
    for _ in range(n):
        template, slots = rng.choice(_TEMPLATES)
        chosen = {slot: _slot_value(slot, rng) for slot in slots}
        # Format the template, tracking offsets as we go. Python's
        # ``str.format`` would lose the offsets, so do it manually.
        text_parts: list[str] = []
        labels: list[dict] = []
        cursor = 0
        i = 0
        while i < len(template):
            if template[i] == "{":
                j = template.index("}", i)
                slot = template[i + 1 : j]
                value = chosen[slot]
                text_parts.append(value.text)
                labels.append(value.to_label(cursor))
                cursor += len(value.text)
                i = j + 1
            else:
                text_parts.append(template[i])
                cursor += 1
                i += 1
        yield {"text": "".join(text_parts), "labels": labels}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--n", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1337)
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for record in generate(args.n, seed=args.seed):
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {args.n} synthetic narratives to {args.out}")


if __name__ == "__main__":
    main()
