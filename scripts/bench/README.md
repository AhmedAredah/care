# PII benchmark harness

Tier-A benchmark for in-tree PII providers. Generates a synthetic
labelled corpus, runs a provider's `detect_text`, and emits a JSON
file shaped like `OCRProvider.accuracy_metrics` that can be assigned
to the provider class directly.

## One-shot

```
python -m scripts.bench.synthetic_corpus --out scripts/bench/data/pii_corpus.jsonl
python -m scripts.bench.run_pii_bench \
    --provider regex \
    --corpus scripts/bench/data/pii_corpus.jsonl \
    --out scripts/bench/data/regex_pii_accuracy.json
```

The output `regex_pii_accuracy.json` is a Tier-A payload — `tier: "A"`
because the corpus and the harness both live in this repo and the
provider was scored end-to-end. Drop it onto the provider:

```python
class RegexPIIProvider(PIIDetectionProvider):
    accuracy_metrics = json.loads(
        (Path(__file__).parent / "regex_pii_accuracy.json").read_text("utf-8")
    )
```

## Limits

The synthetic corpus exercises template-shaped PII inside well-formed
narratives. It does **not** simulate:

- OCR noise (broken VINs across line wraps, dropped digits, character
  confusion between O/0 and I/1)
- Officer abbreviations and partial names ("J. Doe", "JOHNDOE")
- Free-form medical phrases, signatures, hand-printed addresses
- Adversarial examples designed to break a single recognizer

Treat the headline F1 as a floor for "the regex still parses these
exact templates". v0.3.0 should add a held-out labelled set sourced
from a partner DOT before the UI ranks providers across tiers.
