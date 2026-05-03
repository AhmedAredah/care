"""Score in-tree PII providers against a labelled corpus.

Loads a JSONL file produced by ``synthetic_corpus.py``, runs a PII
provider's ``detect_text`` method, and computes precision / recall /
F1 per entity type using overlap matching: a predicted span counts
as a true positive if it overlaps any gold span of the same entity
type, with at least 50% of the smaller span covered by the overlap.

Output is a JSON file in the schema declared by
``OCRProvider.accuracy_metrics`` so it can be dropped onto a
provider class directly:

    {
      "tier": "A",
      "benchmark": "care-pii-bench-v1",
      "benchmark_version": "<corpus-mtime-iso>",
      "metric_name": "f1",
      "headline": <macro-F1>,
      "per_entity": { "PHONE_NUMBER": <f1>, ... },
      "notes": "..."
    }

Usage:
    python -m scripts.bench.run_pii_bench \\
        --provider regex \\
        --corpus scripts/bench/data/pii_corpus.jsonl \\
        --out scripts/bench/data/regex_pii_accuracy.json
"""
from __future__ import annotations

import argparse
import datetime
import json
from collections import defaultdict
from pathlib import Path

from care.pii.registry import get_registry


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def _is_match(pred: dict, gold: dict, *, min_overlap: float = 0.5) -> bool:
    if pred["entity_type"] != gold["entity_type"]:
        return False
    p = (pred["start"], pred["end"])
    g = (gold["start"], gold["end"])
    overlap = _overlap(p, g)
    if overlap == 0:
        return False
    smaller = min(p[1] - p[0], g[1] - g[0])
    return smaller > 0 and overlap / smaller >= min_overlap


def _score(predictions: list[dict], gold: list[dict]) -> tuple[int, int, int]:
    """Return (TP, FP, FN) at the span level using overlap matching."""
    matched_gold: set[int] = set()
    tp = 0
    for pred in predictions:
        hit = False
        for gi, g in enumerate(gold):
            if gi in matched_gold:
                continue
            if _is_match(pred, g):
                matched_gold.add(gi)
                hit = True
                break
        if hit:
            tp += 1
    fp = len(predictions) - tp
    fn = len(gold) - len(matched_gold)
    return tp, fp, fn


def _f1(tp: int, fp: int, fn: int) -> float:
    if tp == 0:
        return 0.0
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def run(provider_name: str, corpus_path: Path) -> dict:
    registry = get_registry()
    cls = registry.get(provider_name)
    provider = cls()
    provider.load({})

    overall = [0, 0, 0]
    per_entity: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])

    with corpus_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            record = json.loads(line)
            entities = provider.detect_text(record["text"])
            preds = [
                {
                    "entity_type": e.entity_type,
                    "start": e.start_offset or 0,
                    "end": e.end_offset or 0,
                }
                for e in entities
            ]
            # Bucket predictions and gold by entity type for per-entity scoring.
            by_type_pred: dict[str, list[dict]] = defaultdict(list)
            by_type_gold: dict[str, list[dict]] = defaultdict(list)
            for p in preds:
                by_type_pred[p["entity_type"]].append(p)
            for g in record["labels"]:
                by_type_gold[g["entity_type"]].append(g)
            for et in set(by_type_pred) | set(by_type_gold):
                tp, fp, fn = _score(by_type_pred.get(et, []), by_type_gold.get(et, []))
                per_entity[et][0] += tp
                per_entity[et][1] += fp
                per_entity[et][2] += fn
                overall[0] += tp
                overall[1] += fp
                overall[2] += fn

    per_entity_f1 = {et: round(_f1(*counts), 3) for et, counts in per_entity.items()}
    headline = round(_f1(*overall), 3)

    corpus_mtime = datetime.datetime.fromtimestamp(corpus_path.stat().st_mtime).date()

    return {
        "tier": "A",
        "benchmark": "care-pii-bench-v1",
        "benchmark_version": corpus_mtime.isoformat(),
        "metric_name": "f1",
        "headline": headline,
        "per_entity": per_entity_f1,
        "notes": (
            f"Synthetic corpus ({corpus_path.name}); span-level overlap match "
            f"with min 50% smaller-side coverage. Provider: {provider_name}."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    result = run(args.provider, args.corpus)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.provider} accuracy -> {args.out}")
    print(f"  headline F1: {result['headline']}")
    for et, score in sorted(result["per_entity"].items()):
        print(f"    {et}: {score}")


if __name__ == "__main__":
    main()
