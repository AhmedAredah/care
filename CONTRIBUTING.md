# Contributing to CARE

Thank you for considering a contribution. CARE has a small surface
area but strict invariants — read the bits below before opening a PR.

## Before you start

Read these in order:

1. [`README.md`](README.md) — what CARE does and what it isn't.
2. [`docs/architecture.md`](docs/architecture.md) — how the pieces
   fit together.
3. [`docs/security.md`](docs/security.md) — the privacy and offline
   commitments every change must preserve.
4. [`SECURITY.md`](SECURITY.md) — what to do if you find a
   vulnerability (do not open a public issue for it).

## Quick start (development)

```bash
git clone https://github.com/AhmedAredah/care
cd care
uv sync                 # core deps
uv sync --extra ml      # optional ML deps
uv run pytest           # full test suite (~3 minutes)
python scripts/governance_check.py
```

## Workflow

1. **Open an issue first** for non-trivial work. Tell us what you want
   to build and why; we'll confirm fit before you sink time into it.
2. **Branch from `main`**: `git checkout -b feat/<short-name>` (or
   `fix/`, `docs/`, `chore/`).
3. **Make the smallest possible change** that satisfies the goal.
   Don't refactor neighbouring code "while you're there"; small PRs
   land faster and review better.
4. **Add or update tests.** A change without tests is unfinished.
5. **Run the full check before pushing**:
   ```bash
   python scripts/governance_check.py
   uv run pytest
   ```
6. **Open the PR** against `main`. Use the PR template.

## Definition of done

A change is not done unless:

- It preserves plugin boundaries (no hard-coded model classes in core
  code).
- It preserves offline / no-network behaviour (no new HTTP calls in
  the default config).
- It preserves fail-closed behaviour (uncertainty must still block
  export).
- It preserves safe public-export behaviour (no original PDFs, no
  unredacted text, no raw PII, no debug artifacts).
- It has tests, or a clearly documented reason tests aren't possible.
- It passes `scripts/governance_check.py` and the full pytest suite.
- It updates docs if it changes user-visible behaviour.

## Style

- Python 3.11+. Use type hints on public functions.
- Default to writing **no** comments. Only add a comment when the
  *why* isn't obvious from the code — a hidden constraint, a
  workaround for a specific bug, behaviour that would surprise a
  reader. Don't explain *what* the code does; well-named identifiers
  do that.
- Don't leave commented-out code, planning notes, or "removed in
  rev X" markers. The git history has those.
- Match existing patterns. If a registry already exists for OCR
  providers, your new OCR provider goes there too — don't invent a
  parallel registry.

## Test policy

- Unit tests for everything in `care/`. Integration tests for the
  pipeline in `tests/integration/`. Policy tests in
  `tests/governance/` (these are the ones that fail CI fast on policy
  regressions).
- Tests must run **offline**. The CI runner has no network
  egress; if your test calls out, it'll fail.
- No real DOT reports, no real PII in fixtures. Generate synthetic
  fixtures programmatically using the helpers in `tests/fixtures/`.
- Don't mock the database/filesystem when a real `tmp_path` works —
  mocked tests pass while the real code path is broken.

## Plugin contributions

Adding a new OCR / PII / document-AI / LLM provider? The interface
specification is in [`docs/plugin-system.md`](docs/plugin-system.md).
The short version:

- Implement the matching ABC fully (don't skip optional methods —
  they're optional in *runtime* terms, not in *interface* terms).
- Register in the appropriate registry; default to **disabled** in
  `config.yaml` if your plugin needs network, paid API keys, or a
  licence-review.
- Set `local_files_only=True` for any Hugging Face model load.
- Add tests that cover the offline path (skip cleanly if your model
  files aren't present in CI, but exercise the offline error path).
- Update [`docs/license-and-model-governance.md`](docs/license-and-model-governance.md)
  if your plugin pulls in a model with a non-MIT/Apache licence.

## Documentation contributions

We're always happy to take doc PRs. The docs live in
[`docs/`](docs/); the [`README.md`](README.md) is the front door. Keep
language plain — DOTs and university researchers are the audience,
not ML engineers.

## Code of conduct

Be kind. Disagree with the idea, never the person. We follow the
[Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).

## Questions

Open a [Discussion](https://github.com/AhmedAredah/care/discussions)
or email `ahmed.aredah@gmail.com`.
